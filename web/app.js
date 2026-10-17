const $ = id => document.getElementById(id);
const state = {projectId:null, flowId:null, runId:null, steps:[], operations:[], flows:[], runs:[], variableNames:[], selectedStep:-1, changedOps:new Set(), view:localStorage.getItem('apiFlowView')||'list', diagram:null};
const pretty = value => JSON.stringify(value, null, 2);
const clear = node => { while (node.firstChild) node.removeChild(node.firstChild); };
const elem = (tag, text, className) => {const node=document.createElement(tag); if(text!==undefined) node.textContent=String(text); if(className) node.className=className; return node;};
const addOption = (select, value, label) => {const option=elem('option',label); option.value=value; select.append(option);};
const stepTones=['primary','success','warning','danger','secondary'];
const defaultTone={http:'primary',manual:'warning',condition:'secondary',foreach:'success'};
const toneForStep=step=>stepTones.includes(step?.tone)?step.tone:defaultTone[step?.kind||'http']||'primary';
let quickEditing=null;
const toast = (message, error=false) => { $('toast').textContent=message; $('toast').classList.toggle('error',error); };
const action = fn => async (...args) => {try {await fn(...args);} catch(error) {toast(error.message,true);offerMissingVariable(error.message);}};
function stepId(){return crypto.randomUUID();}
function openDialog(id){const dialog=$(id);if(!dialog.open)dialog.showModal();}
function closeDialog(id){if($(id).open)$(id).close();}
function offerMissingVariable(message){const match=message?.match(/متغیر\s+([A-Za-z_][A-Za-z0-9_]*)\s+مقدار ندارد/);if(match)openVariable(match[1],null,'این متغیر برای ادامهٔ فلو لازم است. مقدار آن را وارد کنید.');}
function setView(view){if(state.view!==view&&state.selectedStep>=0)saveStep(false);if(view!=='diagram')state.diagram?.setFullscreen(false);state.view=view;localStorage.setItem('apiFlowView',view);$('workspace').classList.toggle('diagram-view',view==='diagram');$('diagramMode').hidden=view!=='diagram';$('listMode').hidden=view==='diagram';$('diagramModeBtn').setAttribute('aria-pressed',view==='diagram');$('listModeBtn').setAttribute('aria-pressed',view==='list');$('sidebarDiagramBtn').classList.toggle('active',view==='diagram');$('sidebarListBtn').classList.toggle('active',view==='list');$('closeInspectorBtn').hidden=view!=='diagram';$('drawerToggle').hidden=view!=='diagram';$('rightbar').classList.remove('drawerOpen');$('stepPanel').classList.remove('inspectorOpen');state.diagram?.render();if(view==='diagram')state.diagram?.focusStart();}
function selectStep(index,openSettings=true){if(state.selectedStep>=0)saveStep(false);state.selectedStep=index;renderSteps();renderStepEditor();if(openSettings){if(state.view==='diagram')$('stepPanel').classList.add('inspectorOpen');else $('stepPanel').scrollIntoView({behavior:'smooth',block:'start'});}}
async function connectSteps(sourceId,port,targetId){saveStep(false);const step=state.steps.find(item=>item._id===sourceId);if(!step)return;step.routes={...(step.routes||{}),[port]:targetId};renderSteps();renderStepEditor();await saveFlow();toast('اتصال ذخیره شد.');}
async function disconnectSteps(sourceId,port){saveStep(false);const step=state.steps.find(item=>item._id===sourceId);if(!step)return;step.routes={...(step.routes||{})};if(port==='error')delete step.routes[port];else step.routes[port]=null;renderSteps();renderStepEditor();await saveFlow();toast(port==='error'?'مسیر خطا حذف شد؛ خطا اجرای فلو را متوقف می‌کند.':'اتصال حذف شد؛ این خروجی فلو را پایان می‌دهد.');}
function makeStep(kind,operation,layout){const base={_id:stepId(),kind,tone:defaultTone[kind]||'primary',name:operation?.summary||({manual:'توقف دستی',condition:'بررسی شرط',foreach:'تکرار روی آرایه',http:'گام HTTP'}[kind]),layout:layout?{...layout,rtl:true}:undefined};if(kind==='http')Object.assign(base,{method:operation?.method||'GET',path:operation?.path||'/'});if(kind==='manual')base.manual_variables=[];if(kind==='condition')base.condition={variable:'',operator:'equals',value:''};if(kind==='foreach')base.loop={list_variable:'',item_variable:'item',index_variable:'item_index',max_iterations:1000};return base;}
function appendStep(kind,operation,layout){requireFlow();if(state.selectedStep>=0)saveStep(false);const step=makeStep(kind,operation,layout|| (state.view==='diagram'?state.diagram?.suggestPosition():undefined));state.steps.push(step);state.selectedStep=state.steps.length-1;renderSteps();renderStepEditor();if(state.view==='diagram')state.diagram?.focusStep(state.selectedStep);else $('stepPanel').scrollIntoView({behavior:'smooth',block:'start'});toast('گام افزوده شد؛ فلو را ذخیره کنید.');return step._id;}
async function api(method,path,body){
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error||`HTTP ${response.status}`);
  return data;
}
function parseEditor(id,fallback){const value=$(id).value.trim();if(!value)return fallback;try{return JSON.parse(value);}catch{throw new Error(`JSON بخش «${id}» معتبر نیست.`);}}
function splitNames(value){return value.split(',').map(x=>x.trim()).filter(Boolean);}
function requireProject(){if(!state.projectId)throw new Error('ابتدا پروژه بسازید یا انتخاب کنید.');}
function requireFlow(){if(!state.flowId)throw new Error('ابتدا فلو بسازید یا انتخاب کنید.');}
function renderGuide(){
  const guide=$('guide');guide.hidden=localStorage.getItem('apiFlowHideGuide')==='1';
  const items=[['پروژه','نام و URL پایه را ذخیره کنید',Boolean(state.projectId)],['Swagger','فایل یا URL مستندات API را وارد کنید',state.operations.length>0],['فلو','endpointها را به‌ترتیب اضافه کنید',state.steps.length>0],['اجرا','متغیرها را پر کنید و فلو را کامل کنید',state.currentRun?.status==='completed']];
  clear($('guideSteps'));items.forEach(([title,detail,done],index)=>{const item=elem('div',undefined,'guideItem'+(done?' done':''));item.append(elem('b',done?'✓':index+1,'guideIndex'),elem('strong',title),elem('small',detail));$('guideSteps').append(item);});
}

async function loadProjects(preferred){
  const projects=await api('GET','/api/projects');
  clear($('projectSelect')); addOption($('projectSelect'),'','انتخاب پروژه');
  for(const project of projects)addOption($('projectSelect'),project.id,project.name);
  const chosen=preferred||state.projectId||localStorage.getItem('apiFlowProject');
  if(projects.some(p=>p.id===chosen)){state.projectId=chosen;$('projectSelect').value=chosen;await loadProject();}
  else {state.projectId=null;state.flowId=null;state.runId=null;$('projectName').value='';$('baseUrl').value='';renderGuide();toast('پروژهٔ تازه بسازید.');}
}
async function loadProject(){
  requireProject();localStorage.setItem('apiFlowProject',state.projectId);state.currentRun=null;
  state.changedOps=new Set();
  const project=await api('GET',`/api/projects/${state.projectId}`);
  $('projectName').value=project.name;$('baseUrl').value=project.base_url;$('refreshJson').value=project.refresh?pretty(project.refresh):'';
  await Promise.all([loadOperations(),loadVariables(),loadFlows(),loadRuns()]);
  $('schemaDiff').textContent=project.schema_version?`نسخهٔ schema: ${project.schema_version}`:'هنوز schema وارد نشده است.';
  renderGuide();
  toast(`پروژهٔ ${project.name} بارگذاری شد.`);
}
async function saveProject(){
  const name=$('projectName').value.trim(),base_url=$('baseUrl').value.trim();
  let project;
  if(state.projectId)project=await api('PUT',`/api/projects/${state.projectId}`,{name,base_url});
  else project=await api('POST','/api/projects',{name,base_url});
  state.projectId=project.id;await loadProjects(project.id);toast('پروژه ذخیره شد.');
}
async function saveRefresh(){requireProject();const refresh=parseEditor('refreshJson',null);await api('PUT',`/api/projects/${state.projectId}`,{refresh});toast('تنظیم تازه‌سازی ذخیره شد.');}
function showSchemaDiff(diff){
  state.changedOps=new Set([...diff.updated,...diff.missing]);
  const lines=[`افزوده: ${diff.added.length}، تغییرکرده: ${diff.updated.length}، غایب: ${diff.missing.length}`];
  if(diff.updated.length)lines.push(`تغییرها: ${diff.updated.slice(0,12).join('، ')}${diff.updated.length>12?' …':''}`);
  if(diff.missing.length)lines.push(`غایب‌ها: ${diff.missing.slice(0,12).join('، ')}${diff.missing.length>12?' …':''}`);
  for(const flow of diff.affected_flows||[])lines.push(`بازبینی فلو «${flow.flow_name}»: گام‌های ${flow.step_indexes.map(i=>i+1).join('، ')}`);
  $('schemaDiff').textContent=lines.join('\n');renderSteps();renderGuide();
}
async function importSchema(text){requireProject();const diff=await api('POST',`/api/projects/${state.projectId}/schema`,{text});showSchemaDiff(diff);await loadOperations();toast('schema وارد شد؛ فلوها و متغیرها حفظ شدند.');}
async function importUrl(){requireProject();const url=$('schemaUrl').value.trim();const diff=await api('POST',`/api/projects/${state.projectId}/schema-url`,{url});showSchemaDiff(diff);await loadOperations();toast('schema از URL دریافت شد.');}
async function loadOperations(){state.operations=await api('GET',`/api/projects/${state.projectId}/operations`);$('operationCount').textContent=state.operations.length;renderOperations();renderSteps();}
function renderOperations(){
  const query=$('operationSearch').value.toLowerCase();clear($('operationList'));
  const matches=state.operations.map((operation,index)=>[index,operation]).filter(([,o])=>(o.path+' '+o.summary+' '+o.method).toLowerCase().includes(query));
  for(const [index,operation] of matches.slice(0,80)){
    const row=elem('div',undefined,'operation'+(operation.missing?' missing':''));
    row.append(elem('span',operation.method,'method '+operation.method),elem('span',' '+operation.path,'path'),elem('small',operation.summary||'بدون عنوان'));
    row.title='کلیک برای افزودن یا کشیدن روی بوم';row.draggable=true;
    row.addEventListener('dragstart',event=>event.dataTransfer.setData('application/x-flow-operation',String(index)));
    row.addEventListener('click',action(async()=>appendStep('http',operation)));$('operationList').append(row);
  }
  if(!query&&state.operations.length>80)$('operationList').append(elem('p','۸۰ مورد نخست نمایش داده شده‌اند؛ برای بقیه جستجو کنید.','hint'));
}
async function loadFlows(preferred){
  state.flows=await api('GET',`/api/projects/${state.projectId}/flows`);clear($('flowSelect'));addOption($('flowSelect'),'','انتخاب فلو');
  for(const flow of state.flows)addOption($('flowSelect'),flow.id,flow.name);
  const chosen=preferred||state.flowId||localStorage.getItem(`apiFlowLastFlow:${state.projectId}`)||state.flows[0]?.id;
  if(state.flows.some(f=>f.id===chosen)){state.flowId=chosen;$('flowSelect').value=chosen;await loadFlow();}
  else {state.flowId=null;state.steps=[];state.selectedStep=-1;$('flowName').value='';renderSteps();renderStepEditor();}
}
async function loadFlow(){
  requireFlow();localStorage.setItem(`apiFlowLastFlow:${state.projectId}`,state.flowId);const flow=await api('GET',`/api/flows/${state.flowId}`);
  state.steps=flow.steps;state.selectedStep=state.steps.length?0:-1;$('flowName').value=flow.name;renderSteps();renderStepEditor();renderStartIndex();
}
async function newFlow(){requireProject();const name=$('newFlowName').value.trim();if(!name)throw new Error('نام فلوی جدید را وارد کنید.');const flow=await api('POST',`/api/projects/${state.projectId}/flows`,{name,steps:[]});$('newFlowName').value='';await loadFlows(flow.id);toast('فلو ساخته شد.');}
async function installClm(){requireProject();const result=await api('POST',`/api/projects/${state.projectId}/preset/clm-v2`,{});await loadFlows(result.flow_id);await loadVariables();const project=await api('GET',`/api/projects/${state.projectId}`);$('refreshJson').value=pretty(project.refresh);toast('نمونهٔ قابل‌ویرایش CLM v2 افزوده شد.');}
async function deleteFlow(){requireFlow();if(!confirm('این فلو و تاریخچهٔ اجراهای آن حذف شود؟'))return;await api('DELETE',`/api/flows/${state.flowId}`);state.flowId=null;state.runId=null;await loadFlows();await loadRuns();toast('فلو حذف شد.');}
async function saveFlow(){requireFlow();saveStep(false);const selected=state.selectedStep;const flow=await api('PUT',`/api/flows/${state.flowId}`,{name:$('flowName').value.trim(),steps:state.steps});await loadFlows(flow.id);state.selectedStep=Math.min(selected,state.steps.length-1);renderSteps();renderStepEditor();toast('فلو و ترتیب گام‌ها ذخیره شد.');}
function moveStep(index,delta){saveStep(false);const target=index+delta;if(target<0||target>=state.steps.length)return;[state.steps[index],state.steps[target]]=[state.steps[target],state.steps[index]];state.selectedStep=target;renderSteps();renderStepEditor();}
function renderSteps(){
  clear($('stepList'));state.steps.forEach((step,index)=>{
    const key=`${step.method||'GET'} ${step.path||''}`;
    const catalog=state.operations.find(o=>`${o.method} ${o.path}`===key);
    const warning=(step.kind||'http')==='http'&&state.operations.length&&(catalog?.missing||!catalog||state.changedOps.has(key));
    const activeRun=state.currentRun?.flow_id===state.flowId?state.currentRun:null;
    const visited=activeRun?.graph_state?.trace||[];
    const row=elem('div',undefined,'step'+(index===state.selectedStep?' selected':'')+(warning?' schemaChanged':'')+(visited.includes(step._id)?' done':'')+(activeRun&&activeRun.status!=='completed'&&index===activeRun.next_index?' current':''));
    const title=elem('div',`${index+1}. ${step.name||step.path||'گام جدید'}`,'stepText');
    title.append(elem('small',step.kind==='manual'?'ورودی دستی':step.kind==='condition'?'شرط · بله / خیر':step.kind==='foreach'?'حلقه · بدنه / پایان':`${step.method||'GET'} ${step.path||''}${warning?' · نیازمند بازبینی schema':''}`));
    title.addEventListener('click',action(async()=>selectStep(index)));
    const tone=elem('span',{'primary':'اصلی','success':'موفقیت','warning':'هشدار','danger':'خطر','secondary':'ثانویه'}[toneForStep(step)],`stepColorChip tone-${toneForStep(step)}`);
    const up=elem('button','↑'),down=elem('button','↓');up.title='بالا';down.title='پایین';
    up.addEventListener('click',action(async()=>moveStep(index,-1)));down.addEventListener('click',action(async()=>moveStep(index,1)));
    row.append(tone,title);
    if((step.kind||'http')==='http'){const curl=elem('button','cURL');curl.title='نمایش و کپی cURL';curl.addEventListener('click',action(async()=>openStepCurl(index)));row.append(curl);}
    row.append(up,down);$('stepList').append(row);
  });$('listCount').textContent=`${state.steps.length} گام`;renderStartIndex();renderGuide();state.diagram?.render();
}
function renderStartIndex(){const old=$('startIndex').value;clear($('startIndex'));state.steps.forEach((step,index)=>addOption($('startIndex'),index,`${index+1}. ${step.name||step.path||'گام'}`));if(old&&Number(old)<state.steps.length)$('startIndex').value=old;}
function renderStepEditor(){
  const step=state.steps[state.selectedStep];$('stepNumber').textContent=step?`گام ${state.selectedStep+1}`:'گامی انتخاب نشده';
  setStepTone(toneForStep(step));resetQuickInput();
  $('stepName').value=step?.name||'';$('stepKind').value=step?.kind||'http';$('stepMethod').value=step?.method||'GET';$('stepPath').value=step?.path||'';
  $('stepBodyMode').value=step?.body_mode||(step?.body!==undefined?'json':'none');$('stepRefresh').checked=Boolean(step?.refresh_on_401);
  $('stepQuery').value=pretty(step?.query||{});$('stepHeaders').value=pretty(step?.headers||{});
  $('stepBody').value=step?.body===undefined?'':pretty(step.body);$('stepFiles').value=pretty(step?.files||{});
  $('stepCaptures').value=pretty(step?.captures||[]);$('stepAssertions').value=pretty(step?.assertions||[]);
  $('manualNames').value=(step?.manual_variables||[]).join(', ');$('manualSensitive').value=(step?.sensitive_variables||[]).join(', ');
  $('conditionVariable').value=step?.condition?.variable||'';$('conditionPath').value=step?.condition?.path||'';
  $('conditionOperator').value=step?.condition?.operator||'equals';$('conditionValue').value=step?.condition?.value===undefined?'':pretty(step.condition.value);
  $('loopListVariable').value=step?.loop?.list_variable||'';$('loopItemVariable').value=step?.loop?.item_variable||'item';
  $('loopIndexVariable').value=step?.loop?.index_variable||'item_index';$('loopMax').value=step?.loop?.max_iterations||1000;
  $('previewOutput').textContent='';updateKind();renderRouteControls();renderRuleLists();renderQuickVariables();renderRequestInputs();
}
function setStepTone(tone){$('stepTone').value=stepTones.includes(tone)?tone:'primary';for(const chip of $('stepToneChips').querySelectorAll('button'))chip.setAttribute('aria-checked',String(chip.dataset.tone===$('stepTone').value));}
function updateKind(){const kind=$('stepKind').value;$('httpFields').hidden=kind!=='http';$('manualFields').hidden=kind!=='manual';$('conditionFields').hidden=kind!=='condition';$('loopFields').hidden=kind!=='foreach';$('stepMethodLabel').hidden=kind!=='http';$('stepPathLabel').hidden=kind!=='http';$('httpHint').hidden=kind!=='http';$('stepMethod').disabled=kind!=='http';$('stepPath').disabled=kind!=='http';renderRouteControls();}
function routePorts(kind){return kind==='condition'?[['yes','اگر بله'],['no','اگر خیر']]:kind==='foreach'?[['body','برای هر عضو'],['done','پس از پایان']]:kind==='manual'?[['next','ادامه']]:[['next','در صورت موفقیت'],['error','در صورت خطا']];}
function renderRouteControls(){
  const area=$('routeControls');clear(area);const step=state.steps[state.selectedStep];if(!step)return;
  const kind=$('stepKind').value;
  for(const [port,label] of routePorts(kind)){
    const row=elem('label',label,'routeRow'),select=elem('select');select.dataset.port=port;
    addOption(select,'__unset__',port==='error'?'توقف با خطا':port==='body'?'اتصال لازم است':'گام بعدی در فهرست');
    addOption(select,'__end__','پایان فلو');
    state.steps.forEach((other,index)=>{if(other._id!==step._id)addOption(select,other._id,`${index+1}. ${other.name||other.path||'گام'}`);});
    const target=step.routes?.[port];select.value=target===undefined?'__unset__':target===null?'__end__':target;
    row.append(select);area.append(row);
  }
}
function saveStep(showToast=true){
  const index=state.selectedStep;if(index<0||!state.steps[index])return;
  const old=state.steps[index],oldId=old._id;
  const kind=$('stepKind').value,name=$('stepName').value.trim()||`گام ${index+1}`;
  let step;
  if(kind==='manual')step={kind,name,manual_variables:splitNames($('manualNames').value),sensitive_variables:splitNames($('manualSensitive').value)};
  else if(kind==='condition')step={kind,name,condition:{variable:$('conditionVariable').value.trim(),path:$('conditionPath').value.trim(),operator:$('conditionOperator').value,value:parseLiteral($('conditionValue').value)}};
  else if(kind==='foreach')step={kind,name,loop:{list_variable:$('loopListVariable').value.trim(),item_variable:$('loopItemVariable').value.trim(),index_variable:$('loopIndexVariable').value.trim(),max_iterations:Number($('loopMax').value)}};
  else {step={kind,name,method:$('stepMethod').value,path:$('stepPath').value.trim(),query:parseEditor('stepQuery',{}),headers:parseEditor('stepHeaders',{}),captures:parseEditor('stepCaptures',[]),assertions:parseEditor('stepAssertions',[]),refresh_on_401:$('stepRefresh').checked};
    const mode=$('stepBodyMode').value;step.body_mode=mode;if(mode!=='none')step.body=parseEditor('stepBody',{});if(mode==='multipart')step.files=parseEditor('stepFiles',{});
  }
  step._id=oldId||stepId();step.tone=$('stepTone').value;if(old.layout)step.layout=old.layout;
  const routes={};for(const select of $('routeControls').querySelectorAll('select')){if(select.value!=='__unset__')routes[select.dataset.port]=select.value==='__end__'?null:select.value;}
  if(Object.keys(routes).length)step.routes=routes;
  state.steps[index]=step;renderSteps();if(showToast)toast('تغییر گام ثبت شد؛ فلو را ذخیره کنید.');
}
function addStep(kind){appendStep(kind);}
async function preview(){requireFlow();saveStep(false);await saveFlow();const reveal=$('revealTimeline').checked?'&reveal=1':'';const result=await api('GET',`/api/flows/${state.flowId}/preview?step=${state.selectedStep}${reveal}`);$('previewOutput').textContent=pretty(result);}
function deleteStep(){if(state.selectedStep<0)return;const removed=state.steps[state.selectedStep]._id;state.steps.splice(state.selectedStep,1);for(const step of state.steps)for(const [port,target] of Object.entries(step.routes||{}))if(target===removed)delete step.routes[port];state.selectedStep=Math.min(state.selectedStep,state.steps.length-1);renderSteps();renderStepEditor();toast('گام حذف شد؛ فلو را ذخیره کنید.');}
function parseLiteral(value){try{return JSON.parse(value);}catch{return value;}}
function updateQuickMode(){const variable=$('quickValueMode').value==='variable';$('quickVariableLabel').hidden=!variable;$('quickLiteralLabel').hidden=variable;}
const inputEditor={body:'stepBody',query:'stepQuery',headers:'stepHeaders'};
const variableReference=value=>typeof value==='string'?value.match(/^\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}$/):null;
function inputEntries(step){
  const entries=[];
  for(const target of ['body','query','headers']){
    if(target==='body'&&step?.body_mode==='none')continue;
    const root=step?.[target];
    if(!root||typeof root!=='object'||Array.isArray(root))continue;
    const visit=(object,path=[])=>{for(const [key,value] of Object.entries(object)){
      const next=[...path,key];
      if(target==='body'&&value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length)visit(value,next);
      else entries.push({target,path:next,value});
    }};
    visit(root);
  }
  return entries;
}
function resetQuickInput(){quickEditing=null;$('quickKey').value='';$('quickVariable').value='';$('quickLiteral').value='';$('quickAddBtn').textContent='افزودن ورودی';$('quickCancelBtn').hidden=true;}
function editQuickInput(entry){
  quickEditing={target:entry.target,path:[...entry.path]};
  $('quickTarget').value=entry.target;$('quickKey').value=entry.path.join('.');
  const variable=variableReference(entry.value);
  $('quickValueMode').value=variable?'variable':'literal';$('quickVariable').value=variable?.[1]||'';
  $('quickLiteral').value=variable?'':pretty(entry.value);updateQuickMode();
  $('quickAddBtn').textContent='ذخیرهٔ ورودی';$('quickCancelBtn').hidden=false;$('quickKey').focus();
}
function removeInputAt(object,path){
  const chain=[object];for(const part of path.slice(0,-1)){if(!chain.at(-1)?.[part])return;chain.push(chain.at(-1)[part]);}
  delete chain.at(-1)[path.at(-1)];
  for(let index=chain.length-1;index>0;index--)if(!Object.keys(chain[index]).length)delete chain[index-1][path[index-1]];
}
function renderRequestInputs(){
  const list=$('requestInputList');clear(list);
  if(state.selectedStep<0||$('stepKind').value!=='http')return;
  let entries;try{entries=inputEntries({...Object.fromEntries(Object.entries(inputEditor).map(([target,id])=>[target,parseEditor(id,{})])),body_mode:$('stepBodyMode').value});}catch{list.append(elem('small','برای مدیریت ورودی‌ها ابتدا JSON نامعتبر را اصلاح کنید.','error'));return;}
  if(!entries.length){list.append(elem('small','هنوز ورودی‌ای تعریف نشده است.','hint'));return;}
  for(const entry of entries){
    const row=elem('div',undefined,'requestInputRow');const name=elem('strong',`${entry.target.toUpperCase()} · ${entry.path.join('.')}`);
    const value=elem('code',variableReference(entry.value)?entry.value:pretty(entry.value));value.title=value.textContent;
    const edit=elem('button','ویرایش');edit.type='button';edit.addEventListener('click',()=>editQuickInput(entry));
    const remove=elem('button','حذف');remove.type='button';remove.addEventListener('click',()=>{const object=parseEditor(inputEditor[entry.target],{});removeInputAt(object,entry.path);$(inputEditor[entry.target]).value=pretty(object);if(quickEditing?.target===entry.target&&quickEditing.path.join('\0')===entry.path.join('\0'))resetQuickInput();renderRequestInputs();toast('ورودی حذف شد؛ گام را ذخیره کنید.');});
    row.append(name,value,edit,remove);
    const names=[...new Set([...(JSON.stringify(entry.value)||'').matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)].map(match=>match[1]))];
    for(const variable of names){const manage=elem('button',`مقدار ${variable}`);manage.type='button';manage.addEventListener('click',action(async()=>{const reveal=$('revealVariables').checked?'?reveal=1':'';const values=await api('GET',`/api/projects/${state.projectId}/variables${reveal}`);openVariable(variable,values[variable]||null,'مقدار این متغیر را وارد یا تغییر دهید.');}));row.append(manage);}
    list.append(row);
  }
}
function editDiagramInput(index,entry){
  selectStep(index,true);
  if(inputEditor[entry.target]){editQuickInput(entry);$('requestInputList').scrollIntoView({block:'nearest'});}
  else {const field={path:'stepPath',manual:'manualNames',condition:'conditionVariable',foreach:'loopListVariable'}[entry.target];$(field)?.focus();}
}
function diagramInputs(step){
  if((step.kind||'http')==='http'){
    const path=[...new Set([...(step.path||'').matchAll(/\{\{?([A-Za-z_][A-Za-z0-9_]*)\}?\}/g)].map(match=>match[1]))].map(name=>({target:'path',path:[name],value:`{${name}}`}));
    return [...path,...inputEntries(step)];
  }
  if(step.kind==='manual')return (step.manual_variables||[]).map(name=>({target:'manual',path:[name],value:`{{${name}}}`}));
  if(step.kind==='condition')return step.condition?.variable?[{target:'condition',path:[step.condition.variable],value:step.condition.operator||'equals'}]:[];
  if(step.kind==='foreach')return step.loop?.list_variable?[{target:'foreach',path:[step.loop.list_variable],value:'آرایه'}]:[];
  return [];
}
function addQuickInput(){
  const target=$('quickTarget').value,key=$('quickKey').value.trim();
  if(!key)throw new Error('نام فیلد ورودی را وارد کنید.');
  const isVariable=$('quickValueMode').value==='variable';
  const name=$('quickVariable').value;
  if(isVariable&&!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name))throw new Error('نام متغیر معتبر نیست.');
  const value=isVariable?`{{${name}}}`:parseLiteral($('quickLiteral').value);
  const editor=inputEditor[target];
  const objects={};for(const part of new Set([target,quickEditing?.target].filter(Boolean))){objects[part]=structuredClone(parseEditor(inputEditor[part],{}));if(!objects[part]||typeof objects[part]!=='object'||Array.isArray(objects[part]))throw new Error('محتوای این بخش باید یک شیء JSON باشد.');}
  const object=objects[target];
  const segments=quickEditing?.target===target&&quickEditing.path.join('.')===key?[...quickEditing.path]:target==='body'?key.split('.'):[key];
  if(segments.some(part=>!part||['__proto__','prototype','constructor'].includes(part)))throw new Error('نام فیلد معتبر نیست.');
  if(quickEditing)removeInputAt(objects[quickEditing.target],quickEditing.path);
  let cursor=object;
  for(const part of segments.slice(0,-1)){if(!cursor[part]||typeof cursor[part]!=='object'||Array.isArray(cursor[part]))cursor[part]={};cursor=cursor[part];}
  cursor[segments.at(-1)]=value;for(const [part,contents] of Object.entries(objects))$(inputEditor[part]).value=pretty(contents);
  if(target==='body'&&$('stepBodyMode').value==='none')$('stepBodyMode').value='json';
  const changed=Boolean(quickEditing);resetQuickInput();renderRequestInputs();toast(`ورودی «${key}» ${changed?'ویرایش':'افزوده'} شد؛ گام را ذخیره کنید.`);
  if(isVariable&&!state.variableNames.includes(name)&&!state.steps.some(step=>(step.captures||[]).some(rule=>rule.name===name)||(step.manual_variables||[]).includes(name)))openVariable(name,null,`برای ورودی «${key}» مقدار متغیر را وارد کنید.`);
}
function renderRuleList(editorId,listId,label){
  const list=$(listId);clear(list);
  let rules;try{rules=parseEditor(editorId,[]);}catch{list.append(elem('small','JSON این بخش نامعتبر است.','error'));return;}
  if(!Array.isArray(rules)){list.append(elem('small','این بخش باید آرایهٔ JSON باشد.','error'));return;}
  rules.forEach((rule,index)=>{
    const row=elem('div',undefined,'rule');row.append(elem('span',label(rule)));
    const remove=elem('button','حذف');remove.title='حذف این قانون';remove.addEventListener('click',()=>{rules.splice(index,1);$(editorId).value=pretty(rules);renderRuleLists();});row.append(remove);list.append(row);
  });
}
function renderRuleLists(){renderRuleList('stepCaptures','captureList',rule=>`${rule.name||'؟'} ← ${rule.path||'$'}${rule.sensitive?' · حساس':''}`);renderRuleList('stepAssertions','assertList',rule=>`${rule.path||'$'} = ${pretty(rule.equals)}`);}
function addCapture(){
  const name=$('captureName').value.trim(),path=$('capturePath').value.trim();
  if(!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)||!path)throw new Error('نام متغیر یا مسیر پاسخ معتبر نیست.');
  const rules=parseEditor('stepCaptures',[]);if(!Array.isArray(rules))throw new Error('JSON خروجی‌ها باید آرایه باشد.');
  rules.push({name,path,sensitive:$('captureSensitive').checked});$('stepCaptures').value=pretty(rules);
  $('captureName').value='';$('capturePath').value='';$('captureSensitive').checked=false;renderRuleLists();renderQuickVariables();toast(`متغیر ${name} به خروجی گام وصل شد.`);
}
function addAssertion(){
  const path=$('assertPath').value.trim();if(!path)throw new Error('مسیر پاسخ را وارد کنید.');
  const rules=parseEditor('stepAssertions',[]);if(!Array.isArray(rules))throw new Error('JSON شرط‌ها باید آرایه باشد.');
  rules.push({path,equals:parseLiteral($('assertValue').value)});$('stepAssertions').value=pretty(rules);
  $('assertPath').value='';$('assertValue').value='';renderRuleLists();toast('شرط پاسخ افزوده شد.');
}
async function uploadStepFile(){
  requireFlow();const file=$('stepUploadFile').files[0],field=$('uploadFieldName').value.trim();
  if(!file||!field)throw new Error('فایل و نام فیلد API را انتخاب کنید.');
  const response=await fetch('/api/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':file.name},body:file});
  const data=await response.json();if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
  const files=parseEditor('stepFiles',{});if(!files||typeof files!=='object'||Array.isArray(files))throw new Error('JSON فایل‌ها باید شیء باشد.');
  files[field]=data.path;$('stepFiles').value=pretty(files);$('stepBodyMode').value='multipart';$('stepUploadFile').value='';
  toast(`فایل ${data.name} افزوده شد؛ گام را ذخیره کنید.`);
}
function renderQuickVariables(){
  const names=new Set(state.variableNames);
  for(const step of state.steps){
    for(const rule of step.captures||[])if(rule.name)names.add(rule.name);
    for(const name of step.manual_variables||[])names.add(name);
    for(const name of [step.condition?.variable,step.loop?.list_variable,step.loop?.item_variable,step.loop?.index_variable])if(name)names.add(name);
  }
  try{for(const rule of parseEditor('stepCaptures',[]))if(rule.name)names.add(rule.name);}catch{}
  for(const match of JSON.stringify(state.steps).matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g))names.add(match[1]);
  clear($('variableSuggestions'));for(const name of [...names].sort())addOption($('variableSuggestions'),name,name);
}
function resetForNewProject(){
  state.projectId=null;state.flowId=null;state.runId=null;state.currentRun=null;state.steps=[];state.operations=[];state.flows=[];state.runs=[];state.variableNames=[];state.selectedStep=-1;
  $('projectSelect').value='';$('projectName').value='';$('baseUrl').value='';$('refreshJson').value='';$('schemaDiff').textContent='';$('flowName').value='';$('operationCount').textContent='0';$('runStatus').textContent='آماده';$('runInfo').textContent='';
  for(const id of ['operationList','flowSelect','runSelect','variableList','manualInputs','timeline'])clear($(id));
  renderSteps();renderStepEditor();renderRunProgress(null);renderQuickVariables();renderGuide();$('projectName').focus();
}

function openVariable(name='',entry=null,hint='مقدار را به‌صورت متن یا JSON وارد کنید.'){$('variableName').value=name;$('variableValue').value=entry&&(!entry.sensitive||$('revealVariables').checked)?pretty(entry.value):'';$('variableSensitive').checked=Boolean(entry?.sensitive);$('variableDialogTitle').textContent=name?`متغیر ${name}`:'تعریف متغیر';$('variableDialogHint').textContent=hint;openDialog('variableDialog');$(name?'variableValue':'variableName').focus();}
async function loadVariables(){const reveal=$('revealVariables').checked;const values=await api('GET',`/api/projects/${state.projectId}/variables${reveal?'?reveal=1':''}`);clear($('variableList'));
  state.variableNames=Object.keys(values).sort();renderQuickVariables();
  for(const [name,entry] of Object.entries(values)){
    const row=elem('div',undefined,'variable');const content=elem('span');content.append(elem('strong',name),elem('code',pretty(entry.value)));
    content.addEventListener('click',()=>openVariable(name,entry,'مقدار جدید را وارد کنید.'));
    const copy=elem('button','کپی');copy.title='کپی کد استفاده از متغیر';copy.addEventListener('click',action(async()=>{await navigator.clipboard.writeText(`{{${name}}}`);toast(`کد متغیر ${name} کپی شد.`);}));
    const remove=elem('button','×');remove.title='حذف متغیر';remove.addEventListener('click',action(async()=>{if(!confirm(`متغیر ${name} حذف شود؟`))return;await api('DELETE',`/api/projects/${state.projectId}/variables/${encodeURIComponent(name)}`);await loadVariables();}));
    row.append(content,copy,remove);$('variableList').append(row);
  }
}
async function saveVariable(){requireProject();const name=$('variableName').value.trim();if(!$('variableValue').value.trim())throw new Error('مقدار متغیر را وارد کنید.');let value;try{value=JSON.parse($('variableValue').value);}catch{value=$('variableValue').value;}await api('POST',`/api/projects/${state.projectId}/variables`,{name,value,sensitive:$('variableSensitive').checked});closeDialog('variableDialog');await loadVariables();toast(`متغیر ${name} ذخیره شد.`);}

const statusLabels={ready:'آماده',running:'در حال اجرا',waiting:'در انتظار ورودی',failed:'نیازمند اصلاح',completed:'کامل شد'};
function renderRunProgress(run){
  const box=$('runProgress');clear(box);if(!run)return;
  const total=run.steps.length,done=run.status==='completed'?total:new Set(run.graph_state?.trace||[]).size,percent=total?Math.round(done/total*100):100;
  const top=elem('div',undefined,'progressLabels');top.append(elem('strong',`${done} از ${total} گام`),elem('span',`${percent}٪`));
  const track=elem('div',undefined,'progressTrack'),fill=elem('span');fill.style.width=`${percent}%`;track.append(fill);box.append(top,track);
  const current=run.steps[run.next_index];if(current)box.append(elem('small',`گام بعدی: ${current.name||current.path||run.next_index+1}`));
}
async function loadRuns(preferred){state.runs=await api('GET',`/api/projects/${state.projectId}/runs`);clear($('runSelect'));addOption($('runSelect'),'','انتخاب اجرا');for(const run of state.runs)addOption($('runSelect'),run.id,`${run.created_at.slice(0,19)} · ${statusLabels[run.status]||run.status} · گام ${run.next_index+1}`);const chosen=preferred||state.runId||state.runs[0]?.id;if(state.runs.some(r=>r.id===chosen)){state.runId=chosen;$('runSelect').value=chosen;await loadRun();}else{state.runId=null;state.currentRun=null;$('runStatus').textContent='آماده';$('runInfo').textContent='';renderRunProgress(null);clear($('manualInputs'));clear($('timeline'));renderSteps();}}
async function loadRun(){if(!state.runId)return;const run=await api('GET',`/api/runs/${state.runId}`);state.currentRun=run;$('runStatus').textContent=statusLabels[run.status]||run.status;$('runStatus').dataset.status=run.status;$('runInfo').textContent=run.error||'';renderRunProgress(run);renderManualInputs(run);renderSteps();await loadTimeline();if(run.status==='waiting'&&run.steps[run.next_index]?.kind==='manual')openDialog('manualDialog');else if(run.status==='waiting')offerMissingVariable(run.error);}
function renderManualInputs(run){clear($('manualInputs'));const step=run.steps[run.next_index];$('openManualBtn').hidden=!step||step.kind!=='manual';if(!step||step.kind!=='manual')return;$('manualDialogHint').textContent=`${step.name||'گام دستی'}: مقدارهای لازم را وارد کنید تا اجرا ادامه یابد.`;for(const name of step.manual_variables||[]){const label=elem('label',name);const input=elem('input');input.className='manualValue';input.dataset.name=name;input.type=(step.sensitive_variables||[]).includes(name)?'password':'text';label.append(input);$('manualInputs').append(label);}}
async function startRun(){requireFlow();await saveFlow();const body={start_index:Number($('startIndex').value||0),acknowledge_post:$('acknowledgePost').checked};const run=await api('POST',`/api/flows/${state.flowId}/runs`,body);state.runId=run.id;await loadRuns(run.id);await advanceRun();}
async function advanceRun(){if(!state.runId)throw new Error('ابتدا اجرای جدید ایجاد یا یک اجرای ذخیره‌شده انتخاب کنید.');const manual_values={};for(const input of $('manualInputs').querySelectorAll('input'))if(input.value)manual_values[input.dataset.name]=input.value;const run=await api('POST',`/api/runs/${state.runId}/advance`,{manual_values,acknowledge_post:$('acknowledgePost').checked});closeDialog('manualDialog');await loadRuns(run.id);toast(run.status==='completed'?'فلو کامل شد.':run.status==='waiting'?'فلو منتظر ورودی یا اصلاح است.':run.status==='failed'?'گام خطا داشت؛ تاریخچه را ببینید.':'اجرا ادامه یافت.');await loadVariables();}
const shellQuote=value=>`'${String(value).replaceAll("'", "'\\''")}'`;
function curlFor(request){
  const body=request.body;
  const preview=request.files!==undefined;
  const files=preview?request.files:(body&&typeof body==='object'&&body.fields&&body.files?body.files:null);
  const multipart=files&&Object.keys(files).length>0;
  const headers={...(request.headers||{})};
  const contentType=Object.keys(headers).find(key=>key.toLowerCase()==='content-type');
  if(multipart&&contentType)delete headers[contentType];
  else if(!multipart&&body!==undefined&&body!==null&&!contentType)headers['Content-Type']='application/json';
  const parts=[`curl --request ${shellQuote(request.method||'GET')} ${shellQuote(request.url)}`];
  for(const [key,value] of Object.entries(headers))parts.push(`--header ${shellQuote(`${key}: ${value}`)}`);
  if(multipart){
    const fields=preview?body:body.fields;
    for(const [key,value] of Object.entries(fields||{}))parts.push(`--form-string ${shellQuote(`${key}=${typeof value==='string'?value:JSON.stringify(value)}`)}`);
    for(const [key,path] of Object.entries(files)){
      const quotedPath=`"${String(path).replaceAll('\\','\\\\').replaceAll('"','\\"')}"`;
      parts.push(`--form ${shellQuote(`${key}=@${quotedPath}`)}`);
    }
  }else if(body!==undefined&&body!==null)parts.push(`--data-raw ${shellQuote(JSON.stringify(body))}`);
  return parts.join(' \\\n  ');
}
function showCurl(request){$('curlOutput').textContent=curlFor(request);$('curlHint').textContent='این دستور شامل مقدارهای واقعی URL، هدرها، بدنه و فایل‌های درخواست است و می‌توانید آن را مستقیم در ترمینال اجرا کنید.';openDialog('curlDialog');}
async function openStepCurl(index){requireFlow();saveStep(false);await saveFlow();const request=await api('GET',`/api/flows/${state.flowId}/preview?step=${index}&reveal=1`);if(request.kind==='manual'||request.kind==='condition'||request.kind==='foreach')throw new Error('این گام درخواست HTTP ندارد.');showCurl(request);}
async function openExchangeCurl(runId,sequence){const exchanges=await api('GET',`/api/runs/${runId}/exchanges?reveal=1`);const item=exchanges.find(exchange=>exchange.sequence===sequence);if(!item)throw new Error('درخواست در تاریخچه یافت نشد.');showCurl({method:item.method,url:item.url,headers:item.request_headers,body:item.request_body});}
async function loadTimeline(){clear($('timeline'));if(!state.runId)return;const reveal=$('revealTimeline').checked;const exchanges=await api('GET',`/api/runs/${state.runId}/exchanges${reveal?'?reveal=1':''}`);for(const item of exchanges){const card=elem('article',undefined,'exchange');const head=elem('header');head.append(elem('span',`#${item.sequence}`,'badge'),elem('span',item.method,'method '+item.method),elem('span',item.step_name),elem('strong',item.response_status??'خطا'));card.append(head,elem('div',item.url,'url'));
    const curl=elem('button','cURL · کپی');const runId=state.runId;curl.addEventListener('click',action(()=>openExchangeCurl(runId,item.sequence)));head.append(curl);
    const request=elem('details');request.open=true;const requestTitle=elem('summary','درخواست · Header و Body');request.append(requestTitle,elem('pre',pretty({headers:item.request_headers,body:item.request_body})));card.append(request);
    const response=elem('details');response.open=true;response.append(elem('summary',`پاسخ · ${item.duration_ms} ms`),elem('pre',pretty({status:item.response_status,headers:item.response_headers,body:item.response_body})));card.append(response);
    if(item.error||item.response_status>=400){const detail=elem('div',undefined,'errorDetail');detail.append(elem('strong',item.error||`HTTP ${item.response_status}`));const body=item.response_body;if(body&&typeof body==='object')for(const key of ['message','detail','code','errors','retry_after'])if(body[key])detail.append(elem('div',`${key}: ${pretty(body[key])}`));card.append(detail);}$('timeline').append(card);
  }}

window.addEventListener('DOMContentLoaded',()=>{
  state.diagram=new DiagramEditor({steps:()=>state.steps,operations:()=>state.operations,flowId:()=>state.flowId,selected:()=>state.selectedStep,current:()=>state.currentRun?.flow_id===state.flowId&&state.currentRun.status!=='completed'?state.currentRun.next_index:-1,
    select:(index,openSettings)=>selectStep(index,openSettings),inputs:diagramInputs,editInput:editDiagramInput,tone:toneForStep,curl:index=>action(()=>openStepCurl(index))(),addOperation:(index,layout)=>appendStep('http',state.operations[index],layout),addKind:(kind,layout)=>appendStep(kind,null,layout),
    connect:(...args)=>action(()=>connectSteps(...args))(),disconnect:(...args)=>action(()=>disconnectSteps(...args))(),error:error=>toast(error.message,true),changed:()=>{renderSteps();toast('چیدمان دیاگرام تغییر کرد؛ فلو را ذخیره کنید.');}});
  setView(state.view);
  $('diagramModeBtn').addEventListener('click',()=>setView('diagram'));
  $('listModeBtn').addEventListener('click',()=>setView('list'));
  $('sidebarDiagramBtn').addEventListener('click',action(()=>{setView('diagram');$('flowToolbar').scrollIntoView({block:'start'});}));
  $('sidebarListBtn').addEventListener('click',action(()=>{setView('list');$('flowToolbar').scrollIntoView({block:'start'});}));
  $('sidebarCatalogBtn').addEventListener('click',()=>$('operationSearch').scrollIntoView({block:'start'}));
  $('sidebarRunBtn').addEventListener('click',()=>{if(state.view==='diagram')$('rightbar').classList.add('drawerOpen');else $('rightbar').scrollIntoView({block:'start'});});
  $('drawerToggle').addEventListener('click',()=>$('rightbar').classList.toggle('drawerOpen'));
  $('closeDrawerBtn').addEventListener('click',()=>$('rightbar').classList.remove('drawerOpen'));
  $('closeInspectorBtn').addEventListener('click',()=>$('stepPanel').classList.remove('inspectorOpen'));
  $('diagramFitBtn').addEventListener('click',()=>{saveStep(false);state.diagram.fit();});
  $('diagramSaveBtn').addEventListener('click',action(saveFlow));
  $('projectSelect').addEventListener('change',action(async()=>{state.projectId=$('projectSelect').value||null;state.flowId=null;state.runId=null;if(state.projectId)await loadProject();else resetForNewProject();}));
  $('newProjectBtn').addEventListener('click',()=>{resetForNewProject();toast('نام و URL پایه را وارد و پروژه را ذخیره کنید.');});
  $('saveProjectBtn').addEventListener('click',action(saveProject));$('saveRefreshBtn').addEventListener('click',action(saveRefresh));
  $('schemaFile').addEventListener('change',action(async event=>{const file=event.target.files[0];if(file)await importSchema(await file.text());}));
  $('importTextBtn').addEventListener('click',action(()=>importSchema($('schemaText').value)));
  $('importUrlBtn').addEventListener('click',action(importUrl));$('operationSearch').addEventListener('input',renderOperations);
  $('newFlowBtn').addEventListener('click',action(newFlow));$('flowSelect').addEventListener('change',action(async()=>{state.flowId=$('flowSelect').value||null;if(state.flowId)await loadFlow();else{state.steps=[];state.selectedStep=-1;$('flowName').value='';renderSteps();renderStepEditor();}}));
  $('installClmBtn').addEventListener('click',action(installClm));$('deleteFlowBtn').addEventListener('click',action(deleteFlow));
  $('saveFlowBtn').addEventListener('click',action(saveFlow));$('addHttpBtn').addEventListener('click',action(()=>addStep('http')));$('addManualBtn').addEventListener('click',action(()=>addStep('manual')));$('addConditionBtn').addEventListener('click',action(()=>addStep('condition')));$('addLoopBtn').addEventListener('click',action(()=>addStep('foreach')));
  $('stepKind').addEventListener('change',updateKind);$('saveStepBtn').addEventListener('click',action(saveFlow));$('previewBtn').addEventListener('click',action(preview));$('stepCurlBtn').addEventListener('click',action(()=>openStepCurl(state.selectedStep)));$('deleteStepBtn').addEventListener('click',action(deleteStep));
  $('quickValueMode').addEventListener('change',updateQuickMode);$('quickAddBtn').addEventListener('click',action(addQuickInput));
  $('quickCancelBtn').addEventListener('click',resetQuickInput);$('stepBodyMode').addEventListener('change',renderRequestInputs);for(const id of Object.values(inputEditor))$(id).addEventListener('input',renderRequestInputs);
  for(const chip of $('stepToneChips').querySelectorAll('button'))chip.addEventListener('click',()=>setStepTone(chip.dataset.tone));
  $('addCaptureBtn').addEventListener('click',action(addCapture));$('addAssertBtn').addEventListener('click',action(addAssertion));$('uploadStepFileBtn').addEventListener('click',action(uploadStepFile));
  $('stepCaptures').addEventListener('input',renderRuleLists);$('stepAssertions').addEventListener('input',renderRuleLists);
  $('saveVariableBtn').addEventListener('click',action(saveVariable));$('newVariableBtn').addEventListener('click',()=>openVariable());$('revealVariables').addEventListener('change',action(loadVariables));
  for(const [button,dialog] of [['closeVariableBtn','variableDialog'],['cancelVariableBtn','variableDialog'],['closeManualBtn','manualDialog'],['cancelManualBtn','manualDialog'],['closeCurlBtn','curlDialog'],['doneCurlBtn','curlDialog']])$(button).addEventListener('click',()=>closeDialog(dialog));
  $('openManualBtn').addEventListener('click',()=>openDialog('manualDialog'));
  $('submitManualBtn').addEventListener('click',action(advanceRun));
  $('copyCurlBtn').addEventListener('click',action(async()=>{await navigator.clipboard.writeText($('curlOutput').textContent);toast('دستور cURL کپی شد.');}));
  $('startRunBtn').addEventListener('click',action(startRun));$('advanceBtn').addEventListener('click',action(advanceRun));$('runSelect').addEventListener('change',action(async()=>{state.runId=$('runSelect').value||null;if(state.runId)await loadRun();else{state.currentRun=null;$('runStatus').textContent='آماده';$('runInfo').textContent='';renderRunProgress(null);clear($('manualInputs'));clear($('timeline'));renderSteps();}}));
  $('revealTimeline').addEventListener('change',action(loadTimeline));
  $('hideGuideBtn').addEventListener('click',()=>{localStorage.setItem('apiFlowHideGuide','1');renderGuide();});
  updateQuickMode();renderGuide();
  loadProjects().catch(error=>toast(error.message,true));
});
