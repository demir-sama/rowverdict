/* RowVerdict 0.2.0 — readable SDK-only React. No bundled framework, mocks or telemetry. */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const React = SDK.React, h = React.createElement;
  const {useState, useEffect} = SDK.hooks;
  const E = (tag, cls, children, props) => h(tag, Object.assign({className: cls || ""}, props || {}), ...(Array.isArray(children) ? children : [children]));
  const text = value => String(value == null ? "" : value);
  const num = value => Number(value || 0).toLocaleString();
  const badge = state => E("span", "rv-badge rv-" + state.toLowerCase(), state);
  const button = (label, fn, disabled, cls, props) => E("button", "rv-btn " + (cls || ""), label, Object.assign({type:"button", onClick:fn, disabled:!!disabled}, props || {}));
  const code = value => E("code", "rv-code", value);
  const json = value => E("pre", "rv-json", JSON.stringify(value, null, 2));
  const field = (id, label, node, hint) => E("div", "rv-field", [E("label", "", label, {htmlFor:id}), node, hint ? E("p", "rv-hint", hint, {id:id+"-hint"}) : null]);
  const labels = {TYPE:"Numeric type", DATE_FORMAT:"Date format", FORMULA:"Formula-like value", EXCEL_FORMULA:"Excel formula (never evaluated)", EXCEL_ERROR:"Excel error cell", EXCEL_DATE:"Invalid / time-bearing Excel date", DUPLICATE_KEY:"Conflicting identifier", REQUIRED:"Required value", ENUM:"Unlisted category", RANGE:"Numeric range", ROW_WIDTH:"Wrong field count"};
  const steps = [["source","Source"],["contract","Contract"],["review","Review"],["replay","Fix & replay"],["export","Export / report"]];
  const base = "/api/plugins/rowverdict";
  async function api(path, payload) {
    return SDK.fetchJSON(base + path, payload === undefined ? undefined : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  }

  function App() {
    const [runs,setRuns]=useState([]), [selected,setSelected]=useState(""), [pane,setPane]=useState("source");
    const [source,setSource]=useState(""), [delimiter,setDelimiter]=useState(","), [sheet,setSheet]=useState("");
    const [inspection,setInspection]=useState(null), [draft,setDraft]=useState(null), [contract,setContract]=useState("");
    const [ack,setAck]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState(""), [notice,setNotice]=useState("");
    const [uploads,setUploads]=useState(false), [historyQuery,setHistoryQuery]=useState(""), [stateFilter,setStateFilter]=useState("ALL");
    const [query,setQuery]=useState(""), [reason,setReason]=useState(""), [offset,setOffset]=useState(0), [quarantine,setQuarantine]=useState(null), [qBusy,setQBusy]=useState(false);
    const [showCells,setShowCells]=useState(false), [edit,setEdit]=useState(null), [patchText,setPatchText]=useState("[]"), [preview,setPreview]=useState(null);
    const run=runs.find(r=>r.id===selected), summary=run ? run.summary : null;
    async function refresh(id) {
      const data=await api("/runs");
      setRuns(data.runs || []); setUploads(!!data.uploads_enabled);
      setSelected(old=>id || ((data.runs || []).some(r=>r.id===old) ? old : ((data.runs || [])[0] || {}).id || ""));
    }
    async function perform(fn) {
      setBusy(true); setError(""); setNotice("");
      try { await fn(); } catch (e) { setError(e && e.message ? e.message : "Request refused. Check input paths, configuration and plan freshness."); }
      finally { setBusy(false); }
    }
    useEffect(()=>{perform(()=>refresh());},[]);
    useEffect(()=>{
      let cancelled=false;
      if (!selected || (pane!=="review" && pane!=="replay")) return;
      setQBusy(true); setQuarantine(null);
      const timer=setTimeout(async()=>{
        try {
          const result=await api("/runs/"+selected+"/quarantine?offset="+offset+"&limit=25&query="+encodeURIComponent(query)+"&code="+encodeURIComponent(reason));
          if (!cancelled) setQuarantine(result);
        } catch(e) { if (!cancelled) {setError(e.message || "Could not load quarantine; check source freshness."); refresh().catch(()=>{});} }
        finally {if(!cancelled)setQBusy(false);}
      },200);
      return ()=>{cancelled=true; clearTimeout(timer);};
    },[selected,pane,query,reason,offset]);
    function chooseRun(id) {setSelected(id);setPane("review");setOffset(0);setQuery("");setReason("");setEdit(null);setPatchText("[]");setPreview(null);setError("");}
    function changeSource(value) {setSource(value);setDraft(null);setInspection(null);setAck(false);}
    async function inspect() {const result=await api("/inspect",{source,delimiter,sheet:sheet || null});setInspection(result);setNotice("All records parsed safely. Choose an explicit contract or create a draft.");}
    async function makeDraft() {
      const result=await api("/drafts",{source,delimiter,sheet:sheet || null});
      setDraft(result);setContract(JSON.stringify(result.suggested_contract,null,2));setAck(false);setPane("contract");
    }
    async function acceptDraft() {
      const result=await api("/drafts/"+draft.draft_id+"/review",{contract:JSON.parse(contract),expected_source_sha256:draft.source_sha256,acknowledgement:"I reviewed this exact contract"});
      setDraft(result);setContract(JSON.stringify(result.reviewed_contract,null,2));setNotice("Your exact source-bound policy review was recorded. Create a plan next; no artifacts have been exported.");
    }
    async function makePlan() {
      const result=await api("/plans",{source,contract:JSON.parse(contract),draft_id:draft ? draft.draft_id : null});
      await refresh(result.id);chooseRun(result.id);setNotice("Plan created. Every record was checked; artifacts still require host approval.");
    }
    async function upload(file) {
      if (!file) return;
      if (!uploads) throw new Error("Dashboard uploads are disabled. Configure allow_dashboard_uploads: true, or enter a path within allowed_roots.");
      if (file.size>20*1024*1024) throw new Error("Input exceeds the 20 MiB limit.");
      const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("Could not read selected file."));reader.readAsDataURL(file);});
      const result=await api("/inputs",{filename:file.name,content_base64:encoded});
      changeSource(result.source);setNotice("File copied only to private local plugin storage. Inspect it or draft a contract next.");
    }
    async function loadContract(file) {
      if (!file) return;
      if (file.size>65536) throw new Error("Contract exceeds 64 KiB.");
      const value=JSON.parse(await file.text());setContract(JSON.stringify(value,null,2));setAck(false);setPane("contract");
    }
    function stageEdit() {
      const patch=JSON.parse(patchText);if(!Array.isArray(patch))throw new Error("Patch must be an array.");
      setPatchText(JSON.stringify([...patch.filter(p=>p.row!==edit.row),{row:edit.row,cells:edit.cells}],null,2));
      setEdit(null);setPreview(null);setPane("replay");setNotice("Correction staged only. Preview and create a new replay plan before asking Hermes to export.");
    }
    async function replay(previewOnly) {
      const result=await api("/runs/"+run.id+"/replays",{patch:JSON.parse(patchText),preview:previewOnly});
      if(previewOnly){setPreview(result.summary);setNotice("Preview only; nothing persisted or exported.");}
      else {await refresh(result.id);chooseRun(result.id);setNotice("New replay plan created. The parent was not changed; host approval is required to export this child plan.");}
    }
    async function downloadReport() {
      const result=await api("/runs/"+run.id+"/report");
      const url=URL.createObjectURL(new Blob([result.html],{type:"text/html;charset=utf-8"}));
      const a=document.createElement("a");a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      setNotice(run.state==="EXPORTED" ? "Downloaded the receipt-verified audit document. Review metadata before sharing." : "Downloaded a clearly marked, unapproved review preview. No clean export was created.");
    }
    const visibleRuns=runs.filter(r=>(stateFilter==="ALL" || r.state===stateFilter) && (r.source+" "+r.id).toLowerCase().includes(historyQuery.toLowerCase()));
    const workflow=E("nav","rv-steps",steps.map(([id,label],i)=>button([E("span","rv-step-no",String(i+1)),label],()=>setPane(id),false,pane===id?"rv-current":"",{key:id,"aria-current":pane===id?"step":undefined})),{"aria-label":"Data review workflow"});
    const sourcePanel=E("section","rv-panel",[
      E("div","rv-section-title",[E("div","",[E("p","rv-kicker","01 / START WITH YOUR DATA"),E("h2","","Choose a local input")]),badge("LOCAL ONLY")]),
      E("p","rv-muted","CSV, Excel .xlsx, flat JSON or JSONL. Nothing leaves this machine. Originals are never edited."),
      E("div","rv-drop",[E("strong","","Drop a file here, or choose one"),E("p","rv-muted",uploads?"Private local upload · 20 MiB maximum":"Uploads disabled by default. Use an allowed path below, or explicitly enable allow_dashboard_uploads."),field("rv-file","Select input file",E("input","",null,{id:"rv-file",type:"file",accept:".csv,.xlsx,.json,.jsonl,.ndjson",disabled:busy || !uploads,onChange:e=>perform(()=>upload(e.target.files[0]))}))],{onDragOver:e=>e.preventDefault(),onDrop:e=>{e.preventDefault();perform(()=>upload(e.dataTransfer.files[0]));}}),
      field("rv-source","Or enter an absolute path",E("input","",null,{id:"rv-source",value:source,onChange:e=>changeSource(e.target.value),placeholder:"/absolute/path/to/your/file.csv",autoComplete:"off",spellCheck:false,"aria-describedby":"rv-source-hint"}),"Must be inside operator-configured allowed_roots. No input directories are enabled by default."),
      E("div","rv-form-row",[field("rv-delimiter","CSV delimiter",E("select","",[E("option","","Comma",{value:","}),E("option","","Semicolon",{value:";"}),E("option","","Tab",{value:"\t"}),E("option","","Pipe",{value:"|"})],{id:"rv-delimiter",value:delimiter,onChange:e=>{setDelimiter(e.target.value);setDraft(null);setAck(false);}})),field("rv-sheet","Excel worksheet (optional for one sheet)",E("input","",null,{id:"rv-sheet",value:sheet,maxLength:100,onChange:e=>{setSheet(e.target.value);setDraft(null);setAck(false);},placeholder:"Exact worksheet name"}))]),
      E("div","rv-actions",[button("Inspect file",()=>perform(inspect),busy || !source),button("Draft a contract →",()=>perform(makeDraft),busy || !source,"rv-primary"),button("Use my own contract",()=>{setPane("contract");setDraft(null);setAck(false);},!source)]),
      inspection ? E("div","rv-result",[E("strong","",num(inspection.input_rows)+" records · "+inspection.columns.length+" columns · "+inspection.input_format),E("p","rv-muted",inspection.columns.join(" / ")),code("Source SHA256: "+inspection.source_sha256)]) : null
    ]);
    const contractPanel=E("section","rv-panel",[
      E("div","rv-section-title",[E("div","",[E("p","rv-kicker","02 / MAKE THE RULES EXPLICIT"),E("h2","","Review the contract")]),draft?badge(draft.status):badge("MANUAL")]),
      E("p","rv-muted",draft?"Inferred from "+draft.sample_rows+" sampled records, not proof of the full dataset. Check date ambiguity, ID strings, enums and required fields. No draft is auto-applied.":"Load or write an explicit ordered contract. An existing source-bound draft must be reviewed before its policy can be used."),
      source?E("p","rv-path",source):E("p","rv-warning","Choose a source file first."),
      field("rv-contract-file","Load a contract JSON file",E("input","",null,{id:"rv-contract-file",type:"file",accept:".json",disabled:busy || (draft && draft.status==="REVIEWED"),onChange:e=>perform(()=>loadContract(e.target.files[0]))})),
      field("rv-contract","Ordered contract JSON",E("textarea","rv-editor",null,{id:"rv-contract",value:contract,rows:16,maxLength:65536,readOnly:!!(draft && draft.status==="REVIEWED"),onChange:e=>{setContract(e.target.value);setAck(false);},spellCheck:false,placeholder:'{"columns":[…],"unique_key":[…],"delimiter":","}'})),
      draft ? E("details","rv-details",[E("summary","","Why these rules were proposed"),...draft.notes.map(n=>E("p","rv-muted",[E("strong","",n.column+": "),n.reason],{key:n.column}))]) : null,
      E("label","rv-check",[E("input","",null,{type:"checkbox",checked:ack,onChange:e=>setAck(e.target.checked)}),"I reviewed this exact contract, including identifiers, dates and category coverage."]),
      draft && draft.status==="DRAFT" ? E("p","rv-warning","DRAFT · Cannot be used until you explicitly record your review below.") : null,
      E("div","rv-actions",[draft && draft.status==="DRAFT"?button("Accept reviewed draft",()=>perform(acceptDraft),busy || !ack || !contract,"rv-primary"):null,button("Create review plan →",()=>perform(makePlan),busy || !source || !contract || !ack || !!(draft && draft.status!=="REVIEWED"),"rv-primary"),draft && draft.status==="REVIEWED"?button("New draft to change policy",()=>perform(makeDraft),busy):null])
    ]);
    const stats=summary ? E("div","rv-stats",[[summary.input_rows,"records checked"],[summary.clean_rows,"clean"],[summary.quarantined_rows,"quarantined"]].map(([n,l])=>E("div","rv-stat",[E("strong","",num(n)),E("span","",l)],{key:l}))) : null;
    const recordTable=E("div","rv-records",[
      E("div","rv-form-row",[field("rv-search","Search quarantine",E("input","",null,{id:"rv-search",type:"search",value:query,maxLength:200,onChange:e=>{setQuery(e.target.value);setOffset(0);},placeholder:"Record, reason or cell value"})),field("rv-reason","Filter reason",E("select","",[E("option","","All reasons",{value:""}),...Object.keys(summary?summary.issue_counts:{}).map(c=>E("option","",labels[c] || c,{key:c,value:c}))],{id:"rv-reason",value:reason,onChange:e=>{setReason(e.target.value);setOffset(0);}}))]),
      E("label","rv-check",[E("input","",null,{type:"checkbox",checked:showCells,onChange:e=>setShowCells(e.target.checked)}),"Reveal sensitive cell values in this local table"]),
      qBusy ? E("p","rv-muted","Loading verified quarantine…",{role:"status"}) : null,
      E("div","rv-table-wrap",E("table","rv-table",[E("caption","rv-sr","Quarantined records under the selected contract"),E("thead","",E("tr","",["Record","Reasons",showCells?"Raw cells":"Raw cells hidden","Action"].map(t=>E("th","",t,{key:t,scope:"col"})))),E("tbody","",quarantine && quarantine.records.length ? quarantine.records.map(r=>E("tr","",[E("td","",code(r.row)),E("td","",[...new Set(r.issues.map(i=>i.code))].map(c=>E("span","rv-reason",labels[c] || c,{key:c}))),E("td","",showCells?E("span","rv-cell",r.cells.join(" · ")):E("span","rv-muted","Sensitive values hidden")),E("td","",button("Correct",()=>{setEdit({row:r.row,cells:(quarantine.columns || []).map((_,i)=>r.cells[i] || "")});setPane("replay");},busy || run.state==="STALE","",{"aria-label":"Correct record "+r.row}))],{key:r.row})):E("tr","",E("td","",qBusy?"Loading…":"No quarantined records match this view.",{colSpan:4})))])),
      E("div","rv-pagination",[E("span","rv-muted",quarantine?num(quarantine.total)+" matching records · showing "+num(quarantine.records.length):""),E("div","rv-actions",[button("← Previous",()=>setOffset(Math.max(0,offset-25)),offset===0 || qBusy),button("Next →",()=>setOffset(offset+25),qBusy || !quarantine || offset+25>=quarantine.total)])])
    ]);
    const reviewPanel=run ? E("section","rv-panel",[
      E("div","rv-section-title",[E("div","",[E("p","rv-kicker","03 / REVIEW EVERY DECISION"),E("h2","",run.source.split("/").pop())]),badge(run.state)]),E("p","rv-path",run.source),stats,
      E("p","rv-conservation",summary.row_conservation?"✓ Row conservation: clean + quarantine = input. Nothing disappears.":"WARNING: row conservation failed."),
      run.state==="STALE"?E("p","rv-warning","This plan is permanently stale. Return to Source and create a new plan."):null,
      E("div","rv-actions",[button("Check freshness",()=>perform(async()=>{try{await api("/runs/"+run.id+"/check");setNotice("Source, policy, engine and any replay patch still match this plan.");}finally{await refresh();}}),busy),button("Use this contract",()=>{changeSource(run.source);setContract(JSON.stringify(run.contract,null,2));setPane("contract");},busy),button("Export / report →",()=>setPane("export"),false,"rv-primary")]),
      E("div","rv-issue-list",Object.entries(summary.issue_counts).map(([c,n])=>button((labels[c] || c)+" · "+num(n),()=>{setReason(reason===c?"":c);setOffset(0);},false,reason===c?"rv-selected":"",{key:c,"aria-pressed":reason===c}))),
      recordTable,
      E("details","rv-details",[E("summary","","Contract, drift and provenance"),E("h3","","Exact policy"),json(run.contract),E("h3","","Drift"),json(run.drift),E("h3","","Source and policy hashes"),code(run.source_sha256),code(run.policy_sha256),summary.replay?json(summary.replay):null])
    ]) : null;
    const replayPanel=run ? E("section","rv-panel",[
      E("p","rv-kicker","04 / CORRECT, RECHECK, THEN REVIEW"),E("h2","","Fix quarantined records"),E("p","rv-muted","Only quarantined records may be corrected. All records are checked again against the same contract and duplicate-key policy. A correction can still fail, or conflict with another row. Parent plans and source files never change."),
      edit ? E("div","rv-edit",[E("h3","","Correct record "+edit.row),E("p","rv-warning","These are sensitive raw values. Formula-like replacements are still quarantined."),...(run.contract.columns || []).map((c,i)=>field("rv-edit-"+i,c.name,E("textarea","",null,{id:"rv-edit-"+i,rows:1,maxLength:65536,value:edit.cells[i] || "",onChange:e=>{const cells=edit.cells.slice();cells[i]=e.target.value;setEdit({...edit,cells});}}))),E("div","rv-actions",[button("Stage this correction",()=>perform(async()=>stageEdit()),busy,"rv-primary"),button("Cancel editing",()=>setEdit(null),false)])]) : null,
      field("rv-patch-file","Load a patch JSON file",E("input","",null,{id:"rv-patch-file",type:"file",accept:".json",disabled:busy,onChange:e=>perform(async()=>{const f=e.target.files[0];if(f.size>20*1024*1024)throw new Error("Patch exceeds 20 MiB.");setPatchText(JSON.stringify(JSON.parse(await f.text()),null,2));setPreview(null);})})),
      field("rv-patch","Staged corrections (JSON)",E("textarea","rv-editor",null,{id:"rv-patch",rows:9,value:patchText,maxLength:20*1024*1024,onChange:e=>{setPatchText(e.target.value);setPreview(null);},spellCheck:false}),"Use logical record numbers, with row + set or row + cells. Wrong-width records need a full cells replacement."),
      E("div","rv-actions",[button("Preview replay",()=>perform(()=>replay(true)),busy || run.state==="STALE"),button("Create new replay plan →",()=>perform(()=>replay(false)),busy || run.state==="STALE","rv-primary"),button("Choose another quarantined row",()=>setPane("review"),false)]),
      preview?E("div","rv-result",[E("strong","","Preview: "+num(preview.clean_rows)+" clean · "+num(preview.quarantined_rows)+" quarantined"),E("p","rv-muted","No artifacts exported. New replay plans require separate native host approval."),json(preview.issue_counts)]):null,
      E("p","rv-warning","Replay creates a review plan, not an approved clean export. Only Hermes can present the approval card for the new plan.")
    ]) : null;
    const exportPanel=run ? E("section","rv-panel",[
      E("p","rv-kicker","05 / EXPLICIT APPROVAL, IMMUTABLE EVIDENCE"),E("div","rv-section-title",[E("h2","",run.receipt?"Approved export receipt":"Continue in Hermes for approval"),badge(run.state)]),stats,
      E("p","rv-muted","This dashboard has no export endpoint and cannot approve a clean export. The host gate binds source, policy, engine and any replay patch to this exact plan."),
      !run.receipt ? E("div","rv-result",[E("strong","","Ask Hermes to run this native tool, then review the approval card:"),field("rv-export-call","Native export request",E("textarea","rv-editor",null,{id:"rv-export-call",rows:2,readOnly:true,value:'rowverdict_export({"plan_id":"'+run.id+'"})',onFocus:e=>e.target.select()})),E("p","rv-muted","/rowverdict export "+run.id+" prepares this same safe handoff; it never dispatches an ungated write.")]) : E("div","rv-result",[E("h3","","Private artifact directory"),code(run.receipt.output_dir),json(run.receipt.artifacts),E("p","rv-muted","clean.csv · quarantine.json · audit.html · receipt.json. Existing approved artifacts are verified rather than overwritten.")]),
      E("div","rv-actions",[button(run.receipt?"Download verified HTML audit":"Download unapproved review preview",()=>perform(downloadReport),busy || run.state==="STALE","rv-primary"),button("Refresh approval status",()=>perform(()=>refresh()),busy)]),
      E("p","rv-warning","Review schema, source paths and category names before sharing the report. Raw row values are excluded, but metadata can still be sensitive."),
      E("details","rv-details",[E("summary","","Source / policy / engine hashes"),json({source_sha256:run.source_sha256,policy_sha256:run.policy_sha256,engine_sha256:summary.engine_sha256,receipt_core_sha256:run.receipt?run.receipt.receipt_core_sha256:undefined})])
    ]) : null;
    const requiresRun=(pane==="review" || pane==="replay" || pane==="export") && !run;
    return E("div","rv",[
      E("header","rv-heading",[E("div","",[E("p","rv-kicker","HERMES / LOCAL DATA OPERATIONS"),E("h1","",["Row",E("span","rv-accent","Verdict")]),E("p","rv-muted","Clean data. Explicit decisions. Evidence that stays.")]),E("div","rv-header-actions",[badge("LOCAL ONLY"),button(busy?"Working…":"↻ Refresh",()=>perform(()=>refresh()),busy)])]),
      E("p","rv-boundary","No uploads to external services · No per-row inference · No silent fixes · Host-approved exports"),
      error?E("div","rv-error",error,{role:"alert"}):null,
      E("div","rv-status",notice,{role:"status","aria-live":"polite"}),
      E("div","rv-shell",[
        E("aside","rv-history",[E("div","rv-section-title",[E("h2","","Run history"),E("span","rv-muted",String(runs.length))]),field("rv-history-search","Find a run",E("input","",null,{id:"rv-history-search",type:"search",value:historyQuery,onChange:e=>setHistoryQuery(e.target.value),placeholder:"File or plan ID"})),field("rv-state","Run state",E("select","",["ALL","PLANNED","EXPORTED","STALE"].map(s=>E("option","",s,{key:s,value:s})),{id:"rv-state",value:stateFilter,onChange:e=>setStateFilter(e.target.value)})),button("+ Start a new input",()=>{setPane("source");setError("");},false,"rv-full"),E("div","rv-run-list",visibleRuns.length?visibleRuns.map(r=>button([E("strong","rv-run-name",r.source.split("/").pop()),badge(r.state),E("span","rv-muted",num(r.summary.clean_rows)+" clean / "+num(r.summary.quarantined_rows)+" held"),E("code","rv-muted",r.id.slice(0,12))],()=>chooseRun(r.id),false,"rv-run "+(selected===r.id?"rv-active":""),{key:r.id,"aria-pressed":selected===r.id})):E("p","rv-muted",runs.length?"No runs match these filters.":"No runs yet. Start with your own file; no fabricated demo data appears here."))]),
        E("main","rv-main",[workflow,requiresRun?E("section","rv-panel rv-empty",[E("h2","","No plan selected"),E("p","rv-muted","Choose a run from history, or inspect your own file and create a contract-bound plan."),button("Choose a source →",()=>setPane("source"),false,"rv-primary")]):pane==="source"?sourcePanel:pane==="contract"?contractPanel:pane==="review"?reviewPanel:pane==="replay"?replayPanel:exportPanel])
      ]),
      E("footer","rv-footer",[E("span","","ROWVERDICT 0.2.0 / DETERMINISTIC BY DESIGN"),E("span","","CSV · XLSX · JSON · JSONL")])
    ],{"aria-busy":busy});
  }
  window.__HERMES_PLUGINS__.register("rowverdict",App);
})();
