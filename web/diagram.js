/* Canvas interactions are kept separate from the form and runner UI. */
window.DiagramEditor = class DiagramEditor {
  constructor(options) {
    this.options = options;
    this.canvas = document.getElementById('diagramCanvas');
    this.viewport = document.getElementById('diagramViewport');
    this.svg = document.getElementById('diagramLinks');
    this.pending = null;
    this.wireDrag = null;
    this.selectedLink = null;
    this.palette = document.getElementById('diagramPalette');
    this.linkMenu = document.getElementById('diagramLinkMenu');
    this.navIndex = 0;
    this.hint = document.getElementById('diagramConnectionHint');
    document.getElementById('diagramCancelConnectionBtn').addEventListener('click', () => this.cancelConnection());
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        if (this.wireDrag) this.endWire(event, true);
        else if (this.pending) this.cancelConnection();
        else if (!this.palette.hidden) this.closePalette();
        else if (!this.linkMenu.hidden) this.closeLinkMenu();
        else if (this.fullscreen) this.setFullscreen(false);
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && this.selectedLink && !event.target.closest('input,textarea,[contenteditable]')) {
        event.preventDefault();
        const {stepId, port} = this.selectedLink;
        this.closeLinkMenu();
        this.options.disconnect(stepId, port);
      }
    });
    this.canvas.addEventListener('dragover', event => event.preventDefault());
    this.canvas.addEventListener('drop', event => {
      event.preventDefault();
      const index = event.dataTransfer.getData('application/x-flow-operation');
      const kind = event.dataTransfer.getData('application/x-flow-kind');
      if (index === '' && !kind) return;
      const point = this.point(event);
      this.addFromPalette(index !== '' ? Number(index) : kind, point, index !== '');
    });
    this.viewport.addEventListener('pointerdown', event => this.beginPan(event));
    document.getElementById('diagramAddBtn').addEventListener('click', () => this.togglePalette());
    document.getElementById('diagramPaletteClose').addEventListener('click', () => this.closePalette());
    document.getElementById('diagramPaletteSearch').addEventListener('input', () => this.renderPalette());
    document.getElementById('diagramFullscreenBtn').addEventListener('click', () => this.setFullscreen(!this.fullscreen));
    document.getElementById('diagramLinkClose').addEventListener('click', () => this.closeLinkMenu());
    document.getElementById('diagramLinkDelete').addEventListener('click', () => {
      if (!this.selectedLink) return;
      const {stepId, port} = this.selectedLink;
      this.closeLinkMenu();
      this.options.disconnect(stepId, port);
    });
    document.getElementById('diagramPrevBtn').addEventListener('click', () => this.focusStep(this.navIndex - 1));
    document.getElementById('diagramNextBtn').addEventListener('click', () => this.focusStep(this.navIndex + 1));
    window.addEventListener('pageshow', event => {
      if (!event.persisted) requestAnimationFrame(() => {
        if (this.options.steps().length) this.focusStart();
      });
    });
    window.addEventListener('resize', () => {this.drawLinks();this.focusStep(this.navIndex);});
  }

  point(event) {
    const box = this.canvas.getBoundingClientRect();
    return {x: Math.max(28, event.clientX - box.left), y: Math.max(28, event.clientY - box.top)};
  }

  suggestPosition() {
    const positions = this.options.steps().map((step, index) => this.position(step, index));
    if (!positions.length) return {x: 85, y: 105};
    const leftmost = Math.min(...positions.map(position => position.x));
    if (leftmost >= 390) return {x: leftmost - 330, y: positions.find(position => position.x === leftmost).y};
    return {x: 85, y: Math.max(...positions.map(position => position.y)) + 260};
  }

  setFullscreen(value) {
    this.fullscreen = Boolean(value);
    document.getElementById('diagramMode').classList.toggle('diagramFullscreen', this.fullscreen);
    document.body.classList.toggle('diagramFullscreenActive', this.fullscreen);
    const button = document.getElementById('diagramFullscreenBtn');
    button.setAttribute('aria-pressed', String(this.fullscreen));
    button.textContent = this.fullscreen ? '⤢ خروج از تمام‌صفحه' : '⛶ تمام‌صفحه';
    this.drawLinks();
  }

  togglePalette(point, link) {
    if (!this.palette.hidden && !point && !link) {this.closePalette();return;}
    this.palettePoint = point || null;
    this.paletteLink = link || null;
    this.closeLinkMenu();
    this.renderPalette();
    this.palette.hidden = false;
    document.getElementById('diagramAddBtn').setAttribute('aria-expanded','true');
    document.getElementById('diagramPaletteSearch').focus();
  }

  closePalette() {
    this.palette.hidden = true;
    this.palettePoint = null;
    this.paletteLink = null;
    document.getElementById('diagramAddBtn').setAttribute('aria-expanded','false');
  }

  renderPalette() {
    const list = document.getElementById('diagramPaletteList');
    const query = document.getElementById('diagramPaletteSearch').value.trim().toLowerCase();
    list.replaceChildren();
    const kinds = [['http','HTTP','درخواست آزاد'],['manual','دستی','ورودی کاربر یا OTP'],['condition','شرط','مسیر بله و خیر'],['foreach','حلقه','تکرار روی آرایه']];
    for (const [kind, title, detail] of kinds) {
      if (!`${title} ${detail} ${kind}`.toLowerCase().includes(query)) continue;
      list.append(this.paletteItem(title, detail, `＋ ${title}`, kind, false));
    }
    const operations = this.options.operations();
    operations.forEach((operation, index) => {
      const label = `${operation.method} ${operation.summary || operation.path}`;
      if (!`${label} ${operation.path}`.toLowerCase().includes(query)) return;
      list.append(this.paletteItem(label, operation.path, operation.method, index, true));
    });
    if (!list.children.length) {const empty = document.createElement('p');empty.className='hint';empty.textContent='گامی با این جستجو پیدا نشد.';list.append(empty);}
  }

  paletteItem(title, detail, badge, value, operation) {
    const button = document.createElement('button');
    button.type = 'button';button.className = 'diagramPaletteItem';button.draggable = true;
    const method = document.createElement('b');method.textContent = badge;
    const text = document.createElement('span');text.textContent = title;
    const small = document.createElement('small');small.textContent = detail;
    button.append(method,text,small);
    button.addEventListener('click', () => this.addFromPalette(value, this.palettePoint || this.suggestPosition(), operation));
    button.addEventListener('dragstart', event => {
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData(operation ? 'application/x-flow-operation' : 'application/x-flow-kind', String(value));
    });
    button.addEventListener('dragend', () => this.closePalette());
    return button;
  }

  addFromPalette(value, point, operation) {
    try {
      const link = this.paletteLink;
      const newId = operation ? this.options.addOperation(value, point) : this.options.addKind(value, point);
      this.closePalette();
      if (link && newId) this.options.connect(link.stepId, link.port, newId);
    } catch (error) {this.options.error(error);}
  }

  beginPan(event) {
    if (event.button !== 0 || event.target.closest('.diagramNode,.diagramPalette,.diagramLinkHit')) return;
    const start = {x:event.clientX,y:event.clientY,left:this.viewport.scrollLeft,top:this.viewport.scrollTop};
    let moved = false;
    const move = current => {
      if (Math.abs(current.clientX-start.x)+Math.abs(current.clientY-start.y)>4) moved = true;
      if (!moved) return;
      this.viewport.classList.add('panning');
      this.viewport.scrollLeft = start.left - (current.clientX-start.x);
      this.viewport.scrollTop = start.top - (current.clientY-start.y);
    };
    const end = () => {window.removeEventListener('pointermove',move);this.viewport.classList.remove('panning');};
    window.addEventListener('pointermove',move);
    window.addEventListener('pointerup',end,{once:true});
  }

  position(step, index) {
    if (step.layout && Number.isFinite(step.layout.x) && Number.isFinite(step.layout.y)) {
      return step.layout.rtl ? step.layout : {x: Math.max(28, 1200 - 265 - step.layout.x), y: step.layout.y};
    }
    return this.defaultPosition(index);
  }

  defaultPosition(index) {
    return {x: 48 + (this.options.steps().length - 1 - index) * 320, y: 90};
  }

  fit() {
    this.options.steps().forEach((step, index) => {step.layout = {...this.defaultPosition(index), rtl:true};});
    this.options.changed();
    this.focusStart();
  }

  focusStart() {
    this.focusStep(0);
    this.viewport.scrollTop = 0;
  }

  focusStep(index) {
    const nodes = [...this.canvas.querySelectorAll('.diagramNode')];
    if (!nodes.length) {this.navIndex = 0;this.updateNavigation();return;}
    this.navIndex = Math.min(Math.max(index, 0), nodes.length - 1);
    const node = nodes[this.navIndex];
    const left = node.offsetLeft + node.offsetWidth - this.viewport.clientWidth + 52;
    this.viewport.scrollLeft = Math.max(0, left);
    this.viewport.scrollTop = Math.max(0, node.offsetTop - 82);
    this.updateNavigation();
  }

  updateNavigation() {
    const steps = this.options.steps();
    document.getElementById('diagramPosition').textContent = `گام ${steps.length ? this.navIndex + 1 : 0} از ${steps.length}`;
    document.getElementById('diagramPrevBtn').disabled = this.navIndex <= 0;
    document.getElementById('diagramNextBtn').disabled = this.navIndex >= steps.length - 1;
    this.canvas.querySelectorAll('.diagramNode').forEach((node, index) => node.classList.toggle('inFocus', index === this.navIndex));
    document.querySelectorAll('#sidebarStepList button').forEach((button, index) => {
      button.classList.toggle('active', index === this.navIndex);
      if (index === this.navIndex) button.setAttribute('aria-current', 'step');
      else button.removeAttribute('aria-current');
    });
  }

  renderNavigator(steps) {
    const rail = document.getElementById('sidebarStepNav');
    const list = document.getElementById('sidebarStepList');
    rail.hidden = !steps.length || document.getElementById('diagramMode').hidden;
    document.getElementById('sidebarStepCount').textContent = `${steps.length} گام`;
    list.replaceChildren();
    steps.forEach((step, index) => {
      const button = this.button(`${index + 1}. ${step.name || step.path || 'گام'}`, () => this.focusStep(index));
      button.title = `نمایش گام ${index + 1} در دیاگرام`;
      list.append(button);
    });
    this.updateNavigation();
  }

  ports(step) {
    switch (step.kind) {
      case 'condition': return [['yes', 'بله'], ['no', 'خیر']];
      case 'foreach': return [['body', 'بدنه'], ['done', 'پایان']];
      case 'manual': return [['next', 'ادامه']];
      default: return [['next', 'موفق'], ['error', 'خطا']];
    }
  }

  routeTarget(step, port, index, steps) {
    if (step.routes && Object.prototype.hasOwnProperty.call(step.routes, port)) return step.routes[port];
    return port !== 'error' && port !== 'body' ? steps[index + 1]?._id || null : null;
  }

  connectionLabel(step, port, index, steps) {
    const targetId = this.routeTarget(step, port, index, steps);
    const targetIndex = steps.findIndex(item => item._id === targetId);
    if (targetIndex >= 0) return `${targetIndex + 1}. ${steps[targetIndex].name || steps[targetIndex].path || 'گام'}`;
    if (port === 'error' && !(step.routes && Object.prototype.hasOwnProperty.call(step.routes, port))) return 'توقف با خطا';
    if (port === 'body' && !(step.routes && Object.prototype.hasOwnProperty.call(step.routes, port))) return 'اتصال لازم';
    return 'پایان فلو';
  }

  updatePending() {
    const active = this.pending && this.options.steps().find(step => step._id === this.pending.stepId);
    if (!active) this.pending = null;
    this.hint.hidden = !this.pending;
    if (this.pending) {
      const port = this.ports(active).find(([name]) => name === this.pending.port);
      document.getElementById('diagramConnectionText').textContent = `خروجی «${port?.[1] || this.pending.port}» از «${active.name || 'گام'}» انتخاب شد. ورودی کارت مقصد را بزنید یا خروجی را روی آن بکشید.`;
    }
    this.canvas.querySelectorAll('.diagramNode').forEach(node => {
      node.classList.toggle('connectTarget', Boolean(this.pending && node.dataset.id !== this.pending.stepId));
      node.classList.toggle('connectSource', Boolean(this.pending && node.dataset.id === this.pending.stepId));
    });
  }

  beginConnection(step, port) {
    if (this.pending?.stepId === step._id && this.pending.port === port) this.pending = null;
    else this.pending = {stepId: step._id, port};
    this.updatePending();
    this.viewport.focus({preventScroll:true});
  }

  startWire(event, step, port) {
    if (event.button !== 0) return;
    event.stopPropagation();
    const origin = {x:event.clientX,y:event.clientY};
    this.wireDrag = {stepId:step._id,port,origin,moved:false};
    const move = current => {
      if (!this.wireDrag) return;
      if (!this.wireDrag.moved && Math.hypot(current.clientX-origin.x,current.clientY-origin.y)<6) return;
      this.wireDrag.moved = true;
      this.pending = {stepId:step._id,port};
      this.updatePending();
      this.drawWirePreview(current);
      const target = document.elementFromPoint(current.clientX,current.clientY)?.closest('.diagramNode');
      this.canvas.querySelectorAll('.diagramNode').forEach(node => node.classList.toggle('wireHover',Boolean(target && node===target && node.dataset.id!==step._id)));
    };
    const end = current => {window.removeEventListener('pointermove',move);this.endWire(current);};
    this.wireDrag.cleanup = () => {window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end);};
    window.addEventListener('pointermove',move);
    window.addEventListener('pointerup',end,{once:true});
  }

  drawWirePreview(event) {
    let preview = this.svg.querySelector('.diagramWirePreview');
    if (!preview) {preview=document.createElementNS('http://www.w3.org/2000/svg','path');preview.setAttribute('class','diagramWirePreview');this.svg.append(preview);}
    const sourceNode = [...this.canvas.querySelectorAll('.diagramNode')].find(node => node.dataset.id===this.wireDrag?.stepId);
    const port = sourceNode?.querySelector(`.diagramPort[data-port="${this.wireDrag?.port}"]`);
    if (!port) return;
    const portRect=port.getBoundingClientRect(), canvasRect=this.canvas.getBoundingClientRect();
    const x1=sourceNode.getBoundingClientRect().left-canvasRect.left,y1=portRect.top+portRect.height/2-canvasRect.top;
    const target=this.point(event);
    const bend=Math.max(45,Math.min(170,Math.abs(target.x-x1)*.45));
    const dir=target.x<x1?-1:1;
    preview.setAttribute('d',`M ${x1} ${y1} C ${x1+dir*bend} ${y1}, ${target.x-dir*bend} ${target.y}, ${target.x} ${target.y}`);
  }

  endWire(event, cancelled=false) {
    const wire=this.wireDrag;
    if (!wire) return;
    wire.cleanup?.();this.wireDrag=null;
    this.svg.querySelector('.diagramWirePreview')?.remove();
    this.canvas.querySelectorAll('.wireHover').forEach(node=>node.classList.remove('wireHover'));
    if (!wire.moved) return;
    this.suppressPortClick=true;
    setTimeout(()=>{this.suppressPortClick=false;},120);
    const target=cancelled?null:document.elementFromPoint(event.clientX,event.clientY)?.closest('.diagramNode');
    this.pending=null;this.updatePending();
    if (cancelled) return;
    if (target && target.dataset.id!==wire.stepId) {this.options.connect(wire.stepId,wire.port,target.dataset.id);return;}
    if (!target && this.viewport.getBoundingClientRect().left<=event.clientX && this.viewport.getBoundingClientRect().right>=event.clientX && this.viewport.getBoundingClientRect().top<=event.clientY && this.viewport.getBoundingClientRect().bottom>=event.clientY) {
      this.togglePalette(this.point(event),{stepId:wire.stepId,port:wire.port});
    }
  }

  showLinkMenu(stepId,port,label,event) {
    this.selectedLink={stepId,port};
    document.getElementById('diagramLinkLabel').textContent=label;
    this.linkMenu.hidden=false;
    this.linkMenu.style.left=`${Math.min(event.clientX+12,window.innerWidth-240)}px`;
    this.linkMenu.style.top=`${Math.min(event.clientY+12,window.innerHeight-64)}px`;
    this.svg.querySelectorAll('.diagramLinkGroup').forEach(group=>group.classList.toggle('active',group.dataset.source===stepId&&group.dataset.port===port));
    this.viewport.focus({preventScroll:true});
  }

  closeLinkMenu() {
    this.selectedLink=null;this.linkMenu.hidden=true;
    this.svg.querySelectorAll('.diagramLinkGroup.active').forEach(group=>group.classList.remove('active'));
  }

  finishConnection(targetId) {
    if (!this.pending || this.pending.stepId === targetId) return;
    const {stepId, port} = this.pending;
    this.pending = null;
    this.updatePending();
    this.options.connect(stepId, port, targetId);
  }

  cancelConnection() {this.pending = null;this.updatePending();}

  render() {
    const steps = this.options.steps();
    if (this.activeFlowId && this.activeFlowId !== this.options.flowId()) this.pending = null;
    this.closeLinkMenu();
    this.canvas.querySelectorAll('.diagramNode').forEach(node => node.remove());
    document.getElementById('diagramEmpty').hidden = steps.length > 0;
    let width = Math.max(1200,this.viewport.clientWidth+280), height = Math.max(520,this.viewport.clientHeight+140);
    steps.forEach((step, index) => {
      const position = this.position(step, index);
      width = Math.max(width, position.x + 350);
      height = Math.max(height, position.y + 270);
      const node = document.createElement('article');
      node.className = `diagramNode ${step.kind || 'http'}${index === this.options.selected() ? ' selected' : ''}${index === this.options.current() ? ' current' : ''}`;
      node.dataset.tone = this.options.tone(step);
      node.dataset.id = step._id;
      node.style.left = `${position.x}px`;
      node.style.top = `${position.y}px`;
      const head = document.createElement('div');
      head.className = 'diagramNodeHead';
      const number = document.createElement('span');number.className='diagramNodeNumber';number.textContent=String(index+1).padStart(2,'0');
      const badge = document.createElement('b');
      badge.className = 'diagramKindChip';
      badge.textContent = {http: step.method || 'GET',manual:'✋ دستی',condition:'◇ شرط',foreach:'↻ حلقه'}[step.kind || 'http'];
      const title = document.createElement('strong');
      title.textContent = step.name || step.path || `گام ${index + 1}`;
      head.append(number,badge, title);
      const summary = document.createElement('small');
      summary.className = 'diagramNodeSummary';
      summary.textContent = step.kind === 'condition' ? `${step.condition?.variable || 'متغیر'} · ${step.condition?.operator || 'equals'}`
        : step.kind === 'foreach' ? `${step.loop?.list_variable || 'آرایه'} → ${step.loop?.item_variable || 'item'}`
        : step.kind === 'manual' ? (step.manual_variables || []).join('، ') || 'ورودی کاربر'
        : step.path || 'مسیر endpoint';
      const meta = document.createElement('div');meta.className = 'diagramNodeMeta';
      const inputs = this.options.inputs(step);
      for(const entry of inputs.slice(0,3)){
        const compact=typeof entry.value==='string'?entry.value:JSON.stringify(entry.value);
        const chip=this.button(`${entry.target.toUpperCase()} · ${entry.path.join('.')} = ${compact} ↗`,()=>this.options.editInput(index,entry));
        chip.className='diagramInputChip';chip.title=`ویرایش ورودی ${entry.path.join('.')}`;meta.append(chip);
      }
      if(inputs.length>3){const more=this.button(`+${inputs.length-3} ورودی`,()=>this.options.select(index,true));more.className='diagramInputChip';meta.append(more);}
      if ((step.kind || 'http') === 'http') {
        const outputs = (step.captures || []).map(rule => rule.name).filter(Boolean);
        for (const [names,prefix] of [[outputs,'خروجی']]) if (names.length) {
          const badge = document.createElement('span');badge.textContent = `${prefix}: ${names.slice(0,3).join('، ')}${names.length>3?' …':''}`;meta.append(badge);
        }
      }
      const actions = document.createElement('div'); actions.className = 'diagramNodeActions';
      const edit = this.button('⚙ تنظیمات', () => this.options.select(index,true));
      edit.className='diagramSettingsButton';
      actions.append(edit);
      if ((step.kind || 'http') === 'http') actions.append(this.button('cURL', () => this.options.curl(index)));
      const input = this.button('◉', () => this.finishConnection(step._id));
      input.className = 'diagramInput';input.title = `ورودی ${step.name || 'گام'}`;
      input.setAttribute('aria-label', `ورودی ${step.name || 'گام'}`);
      const ports = document.createElement('div'); ports.className = 'diagramPorts';
      this.ports(step).forEach(([port, label]) => {
        const row = document.createElement('div');row.className = 'diagramPortRow';
        const button = this.button(`${label} · ${this.connectionLabel(step,port,index,steps)}`, () => {if(!this.suppressPortClick)this.beginConnection(step, port);});
        button.className = `diagramPort port-${port}`;
        button.dataset.port = port;
        button.title = `اتصال خروجی ${label} را تغییر دهید`;
        button.addEventListener('pointerdown', event => this.startWire(event,step,port));
        row.append(button);
        const targetId = this.routeTarget(step, port, index, steps);
        if (targetId) {
          const disconnect = this.button('×', () => {this.cancelConnection();this.options.disconnect(step._id,port);});
          disconnect.className = 'diagramDisconnect';disconnect.title = `حذف اتصال ${label}`;
          disconnect.setAttribute('aria-label', `حذف اتصال ${label}`);
          row.append(disconnect);
        }
        ports.append(row);
      });
      node.append(head, summary, meta, actions, ports, input);
      node.addEventListener('click', event => {
        if (event.target.closest('button')) return;
        this.navIndex = index;this.updateNavigation();
        if (this.pending && this.pending.stepId !== step._id) this.finishConnection(step._id);
        else this.options.select(index,false);
      });
      node.addEventListener('dragover', event => event.preventDefault());
      head.addEventListener('pointerdown', event => this.beginMove(event, node, step));
      this.canvas.append(node);
    });
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    const changedFlow = this.activeFlowId !== this.options.flowId();
    if (changedFlow) {
      this.activeFlowId = this.options.flowId();
      this.navIndex = 0;
    }
    this.renderNavigator(steps);
    if (steps.length && changedFlow) {
      this.focusStart();
      const flowId = this.activeFlowId;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (this.activeFlowId === flowId && this.navIndex === 0) this.focusStart();
      }));
    }
    this.updatePending();
    this.drawLinks();
  }

  button(label, callback) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', event => {event.stopPropagation(); callback();});
    return button;
  }

  beginMove(event, node, step) {
    if (event.button !== 0 || event.target.closest('button')) return;
    event.preventDefault();
    const start = this.position(step, this.options.steps().indexOf(step));
    const origin = {x: event.clientX, y: event.clientY};
    let moved = false;
    const move = current => {
      if (!moved && Math.hypot(current.clientX-origin.x,current.clientY-origin.y)<5) return;
      if (!moved) {moved=true;node.classList.add('moving');this.closeLinkMenu();}
      step.layout = {x: Math.max(20, start.x + current.clientX - origin.x), y: Math.max(20, start.y + current.clientY - origin.y), rtl:true};
      node.style.left = `${step.layout.x}px`; node.style.top = `${step.layout.y}px`;
      this.drawLinks();
    };
    const end = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      node.classList.remove('moving');
      if (moved) this.options.changed();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end, {once:true});
  }

  drawLinks() {
    if (!this.svg) return;
    this.svg.replaceChildren();
    const steps = this.options.steps();
    const byId = new Map(steps.map((step, index) => [step._id, index]));
    const nodeById = new Map([...this.canvas.querySelectorAll('.diagramNode')].map(node => [node.dataset.id, node]));
    const canvasRect = this.canvas.getBoundingClientRect();
    steps.forEach((step, index) => {
      const ports = this.ports(step);
      ports.forEach(([port]) => {
        const targetId = this.routeTarget(step, port, index, steps);
        const targetIndex = byId.get(targetId);
        if (targetIndex === undefined) return;
        const sourceNode = nodeById.get(step._id), targetNode = nodeById.get(targetId);
        const source = sourceNode?.getBoundingClientRect(), target = targetNode?.getBoundingClientRect();
        const portButton = sourceNode?.querySelector(`.diagramPort[data-port="${port}"]`);
        if (!source || !target || !portButton) return;
        const portRect = portButton.getBoundingClientRect();
        const x1 = source.left - canvasRect.left, y1 = portRect.top + portRect.height / 2 - canvasRect.top;
        const targetInput = targetNode.querySelector('.diagramInput').getBoundingClientRect();
        const x2 = targetInput.right - canvasRect.left, y2 = targetInput.top + targetInput.height / 2 - canvasRect.top;
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const bend = Math.min(180, Math.max(24, Math.abs(x2-x1) * .45));
        const direction = x2 < x1 ? -1 : 1;
        const data = `M ${x1} ${y1} C ${x1+direction*bend} ${y1}, ${x2-direction*bend} ${y2}, ${x2} ${y2}`;
        path.setAttribute('d', data);
        path.setAttribute('class', `diagramLink link-${port}`);
        path.setAttribute('marker-end', `url(#arrow-${port === 'error' || port === 'no' ? 'red' : 'blue'})`);
        const group=document.createElementNS('http://www.w3.org/2000/svg','g');
        group.setAttribute('class','diagramLinkGroup');group.dataset.source=step._id;group.dataset.port=port;
        const hit=document.createElementNS('http://www.w3.org/2000/svg','path');
        hit.setAttribute('d',data);hit.setAttribute('class','diagramLinkHit');
        hit.setAttribute('tabindex','0');hit.setAttribute('role','button');
        const label=this.ports(step).find(([name])=>name===port)?.[1]||port;
        hit.setAttribute('aria-label',`اتصال ${label} از گام ${index+1} به گام ${targetIndex+1}`);
        hit.addEventListener('click',event=>{event.stopPropagation();this.showLinkMenu(step._id,port,`گام ${index+1} · ${label} ← گام ${targetIndex+1}`,event);});
        hit.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.showLinkMenu(step._id,port,`گام ${index+1} · ${label} ← گام ${targetIndex+1}`,{clientX:window.innerWidth/2,clientY:window.innerHeight/2});}});
        group.append(path,hit);this.svg.append(group);
      });
    });
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    for (const [name,color] of [['blue','#252525'],['red','#777777']]) {
      const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
      marker.setAttribute('id',`arrow-${name}`);marker.setAttribute('viewBox','0 0 10 10');
      marker.setAttribute('refX','8');marker.setAttribute('refY','5');marker.setAttribute('markerWidth','7');marker.setAttribute('markerHeight','7');marker.setAttribute('orient','auto-start-reverse');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');path.setAttribute('d','M 0 0 L 10 5 L 0 10 z');path.setAttribute('fill',color);
      marker.append(path);defs.append(marker);
    }
    this.svg.prepend(defs);
    this.svg.setAttribute('width',this.canvas.style.width);
    this.svg.setAttribute('height',this.canvas.style.height);
  }
};
