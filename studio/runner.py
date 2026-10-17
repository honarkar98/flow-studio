"""Persistent, project-independent HTTP flow execution."""

from dataclasses import asdict

from .expressions import assert_response, capture, extract, render, valid_name, validate_capture_rules
from .request import build_request


class Runner:
    def __init__(self, store, transport):
        self.store = store
        self.transport = transport

    def _variables(self, project_id):
        return {name: entry["value"] for name, entry in self.store.get_variables(project_id).items()}

    def preview(self, flow_id, step_index):
        flow = self.store.get_flow(flow_id)
        step = flow["steps"][step_index]
        if step.get("kind", "http") == "manual":
            return {"kind": "manual", "manual_variables": step.get("manual_variables", [])}
        if step.get("kind", "http") in ("condition", "foreach"):
            return {"kind": step["kind"], "config": step.get("condition") or step.get("loop"),
                    "routes": step.get("routes", {})}
        project = self.store.get_project(flow["project_id"])
        return asdict(build_request(project, step, self._variables(project["id"])))

    def start(self, flow_id, start_index=0, acknowledge_post=False):
        flow = self.store.get_flow(flow_id)
        if not 0 <= start_index <= len(flow["steps"]):
            raise ValueError("شمارهٔ گام معتبر نیست.")
        if not acknowledge_post:
            for index in range(start_index, len(flow["steps"])):
                step = flow["steps"][index]
                if (step.get("kind", "http") == "http" and step.get("method", "GET").upper() == "POST"
                        and self.store.has_successful_post(flow_id, index)):
                    raise ValueError("اجرای دوبارهٔ POST موفق نیازمند تأیید صریح است.")
        return self.store.create_run(flow_id, start_index, acknowledge_post)

    def _send(self, run, index, name, request, status_on_error="failed", route_error=False):
        exchange = {"step_index": index, "step_name": name, "method": request.method,
                    "url": request.url, "request_headers": request.headers,
                    "request_body": request.body if not request.files else
                    {"fields": request.body, "files": request.files}}
        try:
            response = self.transport.send(request)
        except Exception as exc:
            exchange["error"] = str(exc)
            if route_error:
                return exchange
            self.store.record_attempt(run["id"], exchange, status_on_error, error=str(exc))
            return None
        exchange.update(response_status=response.status, response_headers=response.headers,
                        response_body=response.body, duration_ms=response.duration_ms)
        return exchange

    def _captures(self, response_body, rules, variables):
        changed = capture(response_body, rules, variables)
        return {rule["name"]: (changed[rule["name"]], rule.get("sensitive", False))
                for rule in rules or []}

    def _next(self, run, index, port="next"):
        routes = run["steps"][index].get("routes") or {}
        if port not in routes:
            return index + 1
        target = routes[port]
        if target is None:
            return len(run["steps"])
        for candidate, step in enumerate(run["steps"]):
            if step.get("_id") == target:
                return candidate
        raise ValueError("هدف اتصال در فلو یافت نشد.")

    @staticmethod
    def _graph(run, step):
        graph = run.get("graph_state") or {}
        trace = graph.setdefault("trace", [])
        trace.append(step["_id"])
        if len(trace) > 2000:
            del trace[:-2000]
        return graph

    def _condition(self, step, variables):
        config = step.get("condition") or {}
        name = config.get("variable")
        if not valid_name(name):
            raise ValueError("نام متغیر شرط معتبر نیست.")
        if name not in variables:
            raise ValueError(f"متغیر {name} مقدار ندارد.")
        actual = variables[name]
        if config.get("path"):
            actual = extract(actual, config["path"])
        expected = render(config.get("value"), variables)
        op = config.get("operator", "equals")
        if op == "equals": return actual == expected
        if op == "not_equals": return actual != expected
        if op == "truthy": return bool(actual)
        if op == "exists": return actual is not None
        if op == "contains": return expected in actual
        if op == "greater": return actual > expected
        if op == "less": return actual < expected
        raise ValueError("عملگر شرط معتبر نیست.")

    def _foreach(self, run, index, step, variables):
        config = step.get("loop") or {}
        source = config.get("list_variable")
        item_name = config.get("item_variable", "item")
        index_name = config.get("index_variable", "item_index")
        if not all(valid_name(name) for name in (source, item_name, index_name)):
            raise ValueError("نام متغیرهای حلقه معتبر نیست.")
        graph = run.get("graph_state") or {}
        loops = graph.setdefault("loops", {})
        loop = loops.get(step["_id"])
        if loop is None:
            items = variables.get(source)
            if items is None:
                raise ValueError(f"متغیر {source} مقدار ندارد.")
            if not isinstance(items, list):
                raise ValueError(f"متغیر {source} باید آرایه باشد.")
            limit = config.get("max_iterations", 1000)
            if not isinstance(limit, int) or not 1 <= limit <= 10000:
                raise ValueError("حداکثر تکرار حلقه باید بین ۱ و ۱۰۰۰۰ باشد.")
            if len(items) > limit:
                raise ValueError(f"تعداد اعضای {source} از سقف {limit} بیشتر است.")
            loop = {"items": items, "cursor": 0}
            loops[step["_id"]] = loop
        else:
            loop["cursor"] += 1
        graph = self._graph({**run, "graph_state": graph}, step)
        if loop["cursor"] >= len(loop["items"]):
            del loops[step["_id"]]
            return self._next(run, index, "done"), {}, graph
        if "body" not in (step.get("routes") or {}):
            raise ValueError("خروجی «بدنه» حلقه را به اولین گام تکرار وصل کنید.")
        values = {item_name: (loop["items"][loop["cursor"]], False),
                  index_name: (loop["cursor"], False)}
        return self._next(run, index, "body"), values, graph

    @staticmethod
    def _http_error(exchange):
        status = exchange["response_status"]
        body = exchange.get("response_body")
        parts = [f"HTTP {status}"]
        if isinstance(body, dict):
            for key in ("message", "detail", "error", "code", "errors"):
                value = body.get(key)
                if value:
                    parts.append(f"{key}: {value}")
        elif isinstance(body, str) and body.strip():
            parts.append(body[:300])
        return " · ".join(parts)

    def _execute_http(self, run, project, step, variables, index, acknowledge_post):
        run_id = run["id"]
        if (step.get("method", "GET").upper() == "POST" and not (acknowledge_post or run["allow_post_repeat"])
                and self.store.has_successful_post(run["flow_id"], index, exclude_run_id=run_id)):
            return self.store.update_run(run_id, "waiting", error="اجرای دوبارهٔ POST نیازمند تأیید است.")
        try:
            validate_capture_rules(step.get("captures"))
            request = build_request(project, step, variables)
        except (ValueError, TypeError) as exc:
            return self.store.update_run(run_id, "waiting", error=str(exc))
        exchange = self._send(run, index, step.get("name", step.get("path", "HTTP")), request,
                              route_error="error" in (step.get("routes") or {}))
        if exchange is None:
            return self.store.get_run(run_id)
        if exchange.get("error"):
            next_index = self._next(run, index, "error")
            status = "completed" if next_index >= len(run["steps"]) else "running"
            return self.store.record_attempt(run_id, exchange, status, next_index=next_index,
                                             graph_state=self._graph(run, step))
        refresh = project.get("refresh") if step.get("refresh_on_401") else None
        if exchange["response_status"] == 401 and refresh:
            self.store.record_attempt(run_id, exchange, "running")
            try:
                refresh_request = build_request(project, refresh, variables)
            except (ValueError, TypeError) as exc:
                return self.store.update_run(run_id, "waiting", error=str(exc))
            refresh_exchange = self._send(run, index, "Token refresh", refresh_request, "waiting")
            if refresh_exchange is None:
                return self.store.get_run(run_id)
            if not 200 <= refresh_exchange["response_status"] < 300:
                return self.store.record_attempt(run_id, refresh_exchange, "waiting",
                                                 error="تازه‌سازی توکن ناموفق بود.")
            try:
                refreshed = self._captures(refresh_exchange["response_body"],
                                           refresh.get("captures"), variables)
            except ValueError as exc:
                return self.store.record_attempt(run_id, refresh_exchange, "waiting", error=str(exc))
            self.store.record_attempt(run_id, refresh_exchange, "running", values=refreshed)
            variables.update({key: value for key, (value, _) in refreshed.items()})
            try:
                request = build_request(project, step, variables)
            except (ValueError, TypeError) as exc:
                return self.store.update_run(run_id, "waiting", error=str(exc))
            exchange = self._send(run, index, step.get("name", step.get("path", "HTTP")), request,
                                  route_error="error" in (step.get("routes") or {}))
            if exchange is None:
                return self.store.get_run(run_id)
            if exchange.get("error"):
                next_index = self._next(run, index, "error")
                status = "completed" if next_index >= len(run["steps"]) else "running"
                return self.store.record_attempt(run_id, exchange, status, next_index=next_index,
                                                 graph_state=self._graph(run, step))
        if not 200 <= exchange["response_status"] < 300:
            error = self._http_error(exchange)
            exchange["error"] = error
            if "error" in (step.get("routes") or {}):
                next_index = self._next(run, index, "error")
                graph = self._graph(run, step)
                status = "completed" if next_index >= len(run["steps"]) else "running"
                return self.store.record_attempt(run_id, exchange, status, next_index=next_index,
                                                 graph_state=graph)
            return self.store.record_attempt(run_id, exchange, "failed", error=error)
        try:
            assert_response(exchange["response_body"], step.get("assertions"))
            values = self._captures(exchange["response_body"], step.get("captures"), variables)
        except (ValueError, KeyError, TypeError) as exc:
            return self.store.record_attempt(run_id, exchange, "failed", error=str(exc))
        next_index = self._next(run, index)
        status = "completed" if next_index >= len(run["steps"]) else "running"
        return self.store.record_attempt(run_id, exchange, status, next_index=next_index,
                                         values=values, graph_state=self._graph(run, step))

    def advance(self, run_id, manual_values=None, acknowledge_post=False):
        with self.store.run_lock(run_id):
            return self._advance_locked(run_id, manual_values, acknowledge_post)

    def _advance_locked(self, run_id, manual_values, acknowledge_post):
        self.store.rebase_run(run_id)
        run = self.store.get_run(run_id)
        if run["status"] == "completed":
            return run
        project = self.store.get_project(run["project_id"])
        manual_values = manual_values or {}
        transitions = 0
        while run["next_index"] < len(run["steps"]):
            transitions += 1
            if transitions > 200:
                return self.store.update_run(run_id, "waiting", error="۲۰۰ گام اجرا شد؛ برای ادامه دوباره اجرا را بزنید.")
            index = run["next_index"]
            step = run["steps"][index]
            kind = step.get("kind", "http")
            if kind == "condition":
                try:
                    port = "yes" if self._condition(step, self._variables(project["id"])) else "no"
                    next_index = self._next(run, index, port)
                except (ValueError, TypeError, KeyError) as exc:
                    return self.store.update_run(run_id, "waiting", error=str(exc))
                run = self.store.update_run(run_id, "completed" if next_index >= len(run["steps"]) else "running",
                                            next_index=next_index, graph_state=self._graph(run, step))
                continue
            if kind == "foreach":
                try:
                    next_index, values, graph = self._foreach(run, index, step, self._variables(project["id"]))
                except (ValueError, TypeError, KeyError) as exc:
                    return self.store.update_run(run_id, "waiting", error=str(exc))
                run = self.store.update_run(run_id, "completed" if next_index >= len(run["steps"]) else "running",
                                            next_index=next_index, values=values, graph_state=graph)
                continue
            if step.get("kind", "http") == "manual":
                names = step.get("manual_variables") or []
                if not names or any(name not in manual_values for name in names):
                    return self.store.update_run(run_id, "waiting", error="ورودی دستی لازم است.")
                values = {name: (manual_values[name], name in step.get("sensitive_variables", []))
                          for name in names}
                next_index = self._next(run, index)
                run = self.store.update_run(run_id, "completed" if next_index >= len(run["steps"]) else "running",
                                            next_index=next_index, values=values, graph_state=self._graph(run, step))
                manual_values = {}
                continue
            if step.get("kind", "http") != "http":
                return self.store.update_run(run_id, "failed", error="نوع گام شناخته نشد.")
            run = self._execute_http(run, project, step, self._variables(project["id"]),
                                     index, acknowledge_post)
            if run["status"] != "running":
                return run
        return self.store.update_run(run_id, "completed", next_index=len(run["steps"]))
