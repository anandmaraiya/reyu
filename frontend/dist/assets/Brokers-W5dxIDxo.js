import{u as C,r as n,a as u,j as e}from"./index-DnewPnRh.js";function B({status:o}){const a={live:{label:"Live",color:"#10b981",bg:"rgba(16,185,129,.12)"},beta:{label:"Beta",color:"#f59e0b",bg:"rgba(245,158,11,.12)"},coming_soon:{label:"Coming soon",color:"#94a3b8",bg:"rgba(148,163,184,.12)"}}[o];return e.jsx("span",{style:{display:"inline-block",fontSize:10,fontWeight:600,letterSpacing:".5px",textTransform:"uppercase",padding:"2px 7px",borderRadius:999,color:a.color,background:a.bg},children:a.label})}function L({id:o,name:a,logoUrl:d}){const[p,i]=n.useState(!1);if(p||!d){const c={fyers:"#e63946",zerodha:"#387ed1",angelone:"#c0392b",groww:"#00b386"};return e.jsx("div",{style:{width:48,height:48,borderRadius:12,background:c[o]||"#6366f1",display:"flex",alignItems:"center",justifyContent:"center",fontSize:20,fontWeight:700,color:"#fff"},children:a[0]})}return e.jsx("img",{src:d,alt:a,onError:()=>i(!0),style:{width:48,height:48,objectFit:"contain",borderRadius:8}})}function R({broker:o,connected:a,onConnect:d,onDisconnect:p}){const i=(a==null?void 0:a.status)==="connected",c=o.status==="coming_soon",[l,x]=n.useState(null),[f,m]=n.useState(!1);return n.useEffect(()=>{if(!i){x(null);return}m(!0),u.get(`/api/brokers/${o.id}/profile`).then(v=>x(v.data)).catch(()=>x(null)).finally(()=>m(!1))},[i,o.id]),e.jsxs("div",{className:`broker-card ${i?"broker-card-connected":""}`,children:[e.jsxs("div",{className:"broker-top",children:[e.jsx(L,{id:o.id,name:o.name,logoUrl:o.logo_url}),e.jsxs("div",{className:"broker-info",children:[e.jsx("div",{className:"broker-name",children:o.name}),e.jsxs("div",{className:"broker-badges",children:[e.jsx(B,{status:o.status}),i&&e.jsxs("span",{className:"broker-connected-badge",children:[e.jsx("span",{className:"broker-green-dot"}),"Connected"]})]})]})]}),i&&e.jsx("div",{className:"broker-profile",children:f?e.jsx("div",{className:"broker-profile-loading",children:"Loading account info…"}):l?e.jsxs("div",{className:"broker-funds-row",children:[e.jsxs("div",{className:"broker-fund-item",children:[e.jsx("div",{className:"broker-fund-label",children:"Available"}),e.jsxs("div",{className:"broker-fund-val",children:["₹",l.funds_available.toLocaleString("en-IN")]})]}),e.jsxs("div",{className:"broker-fund-item",children:[e.jsx("div",{className:"broker-fund-label",children:"Used"}),e.jsxs("div",{className:"broker-fund-val used",children:["₹",l.funds_used.toLocaleString("en-IN")]})]}),l.name&&e.jsxs("div",{className:"broker-fund-item",children:[e.jsx("div",{className:"broker-fund-label",children:"Account"}),e.jsx("div",{className:"broker-fund-val",children:l.name})]})]}):null}),e.jsx("div",{className:"broker-actions",children:i?e.jsx("button",{className:"broker-btn broker-btn-disconnect",onClick:()=>p(o.id),children:"Disconnect"}):e.jsx("button",{className:`broker-btn broker-btn-connect ${c?"broker-btn-disabled":""}`,disabled:c,onClick:()=>!c&&d(o.id),children:c?"Coming soon":`Connect ${o.name}`})}),o.status==="beta"&&e.jsx("div",{className:"broker-beta-note",children:"Beta — paper trading only. Orders not executed."})]})}function A(){const{isAuthenticated:o,openGate:a}=C(),[d,p]=n.useState([]),[i,c]=n.useState({}),[l,x]=n.useState(!0),[f,m]=n.useState(""),[v,h]=n.useState(null),[k,w]=n.useState(null),y=(r,s)=>{w({type:r,msg:s}),setTimeout(()=>w(null),4e3)},j=n.useCallback(async()=>{try{const[r,s]=await Promise.allSettled([u.get("/api/brokers/catalog"),o?u.get("/api/brokers/connected"):Promise.resolve({data:{brokers:[]}})]);if(r.status==="fulfilled"&&p(r.value.data.brokers||[]),s.status==="fulfilled"){const b={};for(const t of s.value.data.brokers||[])b[t.broker_id]=t;c(b)}}catch{m("Failed to load broker catalog.")}finally{x(!1)}},[o]);n.useEffect(()=>{j()},[j]);async function N(r){var s,b;if(!o){a({mode:"login",message:"Sign in to connect your broker and get live data.",onSuccess:()=>N(r)});return}h(r);try{const{data:t}=await u.get(`/api/brokers/${r}/oauth-url`);t.url&&(window.location.href=t.url)}catch(t){y("err",((b=(s=t==null?void 0:t.response)==null?void 0:s.data)==null?void 0:b.detail)||"Could not get OAuth URL."),h(null)}}async function S(r){var b,t;const s=d.find(g=>g.id===r);if(confirm(`Disconnect ${(s==null?void 0:s.name)??r}? Live data and orders will stop.`)){h(r);try{await u.delete(`/api/brokers/${r}`),y("ok",`${(s==null?void 0:s.name)??r} disconnected.`),await j()}catch(g){y("err",((t=(b=g==null?void 0:g.response)==null?void 0:b.data)==null?void 0:t.detail)||"Disconnect failed.")}h(null)}}const z=Object.values(i).filter(r=>r.status==="connected").length;return e.jsxs("div",{className:"brokers-page",children:[k&&e.jsxs("div",{className:`sub-toast ${k.type==="ok"?"sub-toast-ok":"sub-toast-err"}`,children:[k.type==="ok"?"✓":"⚠"," ",k.msg]}),e.jsxs("div",{className:"brokers-header",children:[e.jsxs("div",{children:[e.jsx("h1",{className:"brokers-title",children:"Broker Connections"}),e.jsx("p",{className:"brokers-subtitle",children:"Connect your broker to get live quotes, positions, and one-click order execution. All credentials are stored encrypted — Reyu.ai never sees your passwords."})]}),z>0&&e.jsxs("div",{className:"brokers-conn-badge",children:[e.jsx("span",{className:"broker-green-dot"}),z," connected"]})]}),!o&&e.jsxs("div",{className:"brokers-anon-nudge",children:[e.jsx("span",{className:"brokers-anon-icon",children:"🔗"}),e.jsxs("div",{children:[e.jsx("strong",{children:"Sign in to connect a broker"}),e.jsx("div",{style:{fontSize:13,color:"var(--color-text-muted)",marginTop:2},children:"You're browsing in demo mode. Sign in to link your Fyers or Zerodha account."})]}),e.jsx("button",{className:"brokers-signin-btn",onClick:()=>a({mode:"login"}),children:"Sign in"})]}),l&&e.jsxs("div",{className:"brokers-loading",children:[e.jsx("div",{className:"brokers-spinner"}),"Loading broker catalog…"]}),f&&e.jsx("div",{className:"brokers-error",children:f}),!l&&e.jsxs("div",{className:"brokers-grid",children:[d.map(r=>e.jsx("div",{style:{opacity:v===r.id?.6:1,transition:"opacity .2s"},children:e.jsx(R,{broker:r,connected:i[r.id],onConnect:N,onDisconnect:S})},r.id)),d.length===0&&!l&&e.jsx("div",{className:"brokers-empty",children:"No brokers available — check backend config."})]}),e.jsxs("div",{className:"brokers-how",children:[e.jsx("h2",{className:"brokers-how-title",children:"How it works"}),e.jsx("div",{className:"brokers-how-steps",children:[{n:"1",title:"Click Connect",body:"You're redirected to your broker's login page. We never see your credentials."},{n:"2",title:"Authorize Reyu",body:"Grant read/trade permissions on the broker's official OAuth screen."},{n:"3",title:"Live data flows",body:"Real-time quotes, option chain, OI, and IV data appear across the platform."},{n:"4",title:"Place orders",body:"One-click hedge builder, strike selection, and paper-to-live escalation."}].map(r=>e.jsxs("div",{className:"brokers-step",children:[e.jsx("div",{className:"brokers-step-num",children:r.n}),e.jsxs("div",{children:[e.jsx("div",{className:"brokers-step-title",children:r.title}),e.jsx("div",{className:"brokers-step-body",children:r.body})]})]},r.n))})]}),e.jsx("style",{children:`
        .brokers-page {
          max-width: 960px;
          margin: 0 auto;
          padding: 32px 20px 60px;
        }
        .brokers-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 24px;
          flex-wrap: wrap;
        }
        .brokers-title { font-size: 24px; font-weight: 700; margin: 0 0 6px; }
        .brokers-subtitle { font-size: 14px; color: var(--color-text-muted); margin: 0; max-width: 620px; line-height: 1.5; }
        .brokers-conn-badge {
          display: flex; align-items: center; gap: 6px;
          background: rgba(16,185,129,.1); border: 1px solid rgba(16,185,129,.25);
          padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 500;
          color: var(--color-success); white-space: nowrap; flex-shrink: 0;
        }
        .broker-green-dot {
          display: inline-block; width: 7px; height: 7px;
          background: #10b981; border-radius: 50%;
          box-shadow: 0 0 0 2px rgba(16,185,129,.25);
        }

        .brokers-anon-nudge {
          display: flex; align-items: center; gap: 12px;
          background: var(--color-bg-card); border: 1px solid var(--color-border);
          border-radius: 12px; padding: 14px 18px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .brokers-anon-icon { font-size: 22px; flex-shrink: 0; }
        .brokers-anon-nudge > div { flex: 1; min-width: 200px; }
        .brokers-signin-btn {
          background: var(--color-primary); color: #fff;
          border: none; border-radius: 8px; padding: 8px 16px;
          font-size: 13px; font-weight: 600; cursor: pointer;
          flex-shrink: 0;
        }
        .brokers-signin-btn:hover { filter: brightness(1.08); }

        .brokers-loading {
          display: flex; align-items: center; gap: 10px;
          color: var(--color-text-muted); font-size: 14px; padding: 40px 0;
          justify-content: center;
        }
        .brokers-spinner {
          width: 18px; height: 18px; border: 2px solid var(--color-border);
          border-top-color: var(--color-primary); border-radius: 50%;
          animation: spin .7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .brokers-error {
          background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.25);
          border-radius: 10px; padding: 12px 16px; color: var(--color-danger);
          margin-bottom: 20px; font-size: 14px;
        }
        .brokers-empty { color: var(--color-text-muted); text-align: center; padding: 40px 0; }

        .brokers-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
          gap: 16px;
          margin-bottom: 40px;
        }

        /* Broker card */
        .broker-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px;
          padding: 20px;
          transition: box-shadow .2s, border-color .2s;
        }
        .broker-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,.1); }
        .broker-card-connected {
          border-color: rgba(16,185,129,.35);
          box-shadow: 0 0 0 1px rgba(16,185,129,.15);
        }
        .broker-top {
          display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
        }
        .broker-info { flex: 1; min-width: 0; }
        .broker-name { font-size: 16px; font-weight: 600; margin-bottom: 5px; }
        .broker-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .broker-connected-badge {
          display: flex; align-items: center; gap: 4px;
          font-size: 11px; font-weight: 600; color: var(--color-success);
        }

        .broker-profile {
          background: var(--color-bg-base);
          border: 1px solid var(--color-border);
          border-radius: 8px; padding: 10px 12px; margin-bottom: 14px;
        }
        .broker-profile-loading { font-size: 12px; color: var(--color-text-muted); }
        .broker-funds-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .broker-fund-item { flex: 1; min-width: 80px; }
        .broker-fund-label { font-size: 10px; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 2px; }
        .broker-fund-val { font-size: 14px; font-weight: 600; }
        .broker-fund-val.used { color: var(--color-danger); }

        .broker-actions { margin-bottom: 6px; }
        .broker-btn {
          width: 100%; padding: 9px; border-radius: 8px;
          font-size: 13px; font-weight: 600; cursor: pointer;
          border: none; transition: all .15s;
        }
        .broker-btn-connect {
          background: var(--color-primary); color: #fff;
          box-shadow: 0 2px 8px rgba(16,185,129,.25);
        }
        .broker-btn-connect:hover:not(.broker-btn-disabled) { filter: brightness(1.08); }
        .broker-btn-disconnect {
          background: none; border: 1px solid var(--color-border);
          color: var(--color-text-muted);
        }
        .broker-btn-disconnect:hover { border-color: var(--color-danger); color: var(--color-danger); }
        .broker-btn-disabled { background: var(--color-bg-base); color: var(--color-text-muted); cursor: default; border: 1px solid var(--color-border); box-shadow: none; }

        .broker-beta-note {
          font-size: 11px; color: rgba(245,158,11,.8);
          margin-top: 8px; text-align: center;
        }

        /* How it works */
        .brokers-how {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px; padding: 24px 28px;
        }
        .brokers-how-title { font-size: 16px; font-weight: 600; margin: 0 0 18px; }
        .brokers-how-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
        .brokers-step { display: flex; gap: 12px; align-items: flex-start; }
        .brokers-step-num {
          width: 28px; height: 28px; border-radius: 50%;
          background: var(--color-primary); color: #fff;
          display: flex; align-items: center; justify-content: center;
          font-size: 12px; font-weight: 700; flex-shrink: 0;
        }
        .brokers-step-title { font-size: 13px; font-weight: 600; margin-bottom: 3px; }
        .brokers-step-body { font-size: 12px; color: var(--color-text-muted); line-height: 1.5; }

        /* Reuse sub-toast from Subscription */
        .sub-toast {
          position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
          z-index: 9999; padding: 10px 20px; border-radius: 8px;
          font-size: 14px; font-weight: 500;
          animation: toastIn .2s ease;
        }
        .sub-toast-ok { background: var(--color-success); color: #fff; }
        .sub-toast-err { background: var(--color-danger); color: #fff; }
        @keyframes toastIn { from { opacity:0; transform: translateX(-50%) translateY(-8px); } to { opacity:1; transform: translateX(-50%) translateY(0); } }

        @media (max-width: 600px) {
          .brokers-grid { grid-template-columns: 1fr; }
          .brokers-how-steps { grid-template-columns: 1fr; }
        }
      `})]})}export{A as default};
