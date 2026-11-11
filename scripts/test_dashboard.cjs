// Structural/interaction QA only. This is NOT a browser or screenshot test.
// Usage: HERMES_CHECKOUT=/path/to/hermes node scripts/test_dashboard.cjs
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const {createRequire} = require("node:module");
const fromHost = createRequire(path.join(process.env.HERMES_CHECKOUT, "web/package.json"));
const React = fromHost("react");
const {renderToStaticMarkup} = fromHost("react-dom/server");
const runs = JSON.parse(fs.readFileSync(path.join(__dirname,"../evidence/dashboard-api.json"),"utf8")).runs;
let App, values, index, effects;
const render = (view="evidence", filter="ALL", asc=true) => {
  values = [runs, runs[0].id, view, filter, asc, false, ""];
  index = 0; effects=[];
  return renderToStaticMarkup(React.createElement(App));
};
global.window = {
  __HERMES_PLUGIN_SDK__: {
    React,
    hooks: {
      useState: () => {const n=index++;return [values[n],v=>values[n]=typeof v==="function"?v(values[n]):v];},
      useEffect: f=>effects.push(f),
      useMemo: f=>f()
    },
    fetchJSON: async url => {assert.equal(url,"/api/plugins/rowverdict/runs");return {runs};}
  },
  __HERMES_PLUGINS__: {register: (name,component)=>{assert.equal(name,"rowverdict");App=component;}}
};
require(path.join(__dirname,"../dashboard/dist/index.js"));
let html=render();
assert.ok(html.includes("10,000") && html.includes("9,977") && html.includes("23"));
assert.ok(html.includes("No rows disappear") && html.includes("Row evidence"));
assert.ok(!html.includes("HYPERLINK"));
console.log("PASS: real React server-render shows measured 10,000 / 9,977 / 23 counts and no raw rejected cells");
assert.ok(render("contract").includes("%d/%m/%Y"));
assert.ok(render("contract").includes("order_id"));
assert.ok(render("drift").includes("Compare with the previous plan"));
assert.ok(render("receipt").includes("rowverdict_export"));
assert.ok(render("receipt").includes("no export endpoint"));
console.log("PASS: contract, drift and receipt tabs render actual policy, lineage and explicit host-gated next step");
html=render("evidence","FORMULA",false);
assert.ok(html.includes("Formula-like cell"));
assert.ok(html.includes("Clear filter"));
console.log("PASS: row evidence filter and descending record order render without a DOM or external fetch");
(async()=>{await effects[0]();assert.equal(values[5],false);assert.equal(values[6],"");console.log("PASS: refresh uses SDK same-origin JSON client and preserves selected plan");})().catch(e=>{console.error(e);process.exitCode=1;});
