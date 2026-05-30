// ════════════════════════════════════════════════════════════════════════
// data.jsx — Tata Precision Auto Components dataset (extended for all stages)
// One mock store. Real-ish figures, INR, TN automotive context.
// ════════════════════════════════════════════════════════════════════════
const M = {
  company:'Tata Precision Auto Components Pvt. Ltd.',
  short:'TPAC', city:'Chennai, TN', currency:'₹', fy:'FY 26-27',
  updated:'30 May 2026 · 14:32 IST', cin:'U34300TN2018PTC124589', gstin:'33AAACT2727Q1ZV',

  // ── top-level nav: Home + 11 workflow stages (handoff §4 target IA) ──
  stages:[
    { id:'home',       n:'00', name:'Home',        sub:'Command center · readiness' },
    { id:'setup',      n:'01', name:'Setup',       sub:'Company · calendar · MSME' },
    { id:'products',   n:'02', name:'Products',    sub:'BOM · costs · SKU · MTO' },
    { id:'demand',     n:'03', name:'Demand',      sub:'Forecast · ABC/XYZ · events' },
    { id:'plan',       n:'04', name:'Plan',        sub:'S&OP · level-vs-chase' },
    { id:'production', n:'05', name:'Production',   sub:'Lines · stages · MPS' },
    { id:'sourcing',   n:'06', name:'Sourcing',    sub:'Suppliers · landed · OTIF' },
    { id:'logistics',  n:'07', name:'Logistics',   sub:'Nodes · lanes · 3PL · CoG' },
    { id:'finance',    n:'08', name:'Finance',     sub:'Cash · capital · NPV · FX' },
    { id:'console',    n:'09', name:'Console',     sub:'7 solvers · MILP/LP run' },
    { id:'scenarios',  n:'10', name:'Scenarios',   sub:'Risk · cost · what-if' },
    { id:'reference',  n:'11', name:'Reference',   sub:'Learning Lab · SAP map' },
  ],

  // ── solver pipeline ribbon (P6): the product spine ──
  pipeline:[
    { id:'demand',   stage:'DEMAND',    sub:'17 models', status:'done',    val:'MAPE 6.8%', go:'demand' },
    { id:'aggregate',stage:'AGGREGATE', sub:'S&OP',      status:'done',    val:'Level-mix', go:'plan' },
    { id:'profit',   stage:'PROFIT',    sub:'LP',        status:'done',    val:'₹6.84 Cr',  go:'console' },
    { id:'procure',  stage:'PROCURE',   sub:'MILP',      status:'running', val:'128 POs',   go:'console' },
    { id:'produce',  stage:'PRODUCE',   sub:'MILP',      status:'queued',  val:'3 lines',   go:'console' },
    { id:'ship',     stage:'SHIP',      sub:'Transport', status:'queued',  val:'—',         go:'logistics' },
  ],

  // ── headline KPIs ──
  kpis:{ totalCost:'₹ 12.64 Cr', savings:'₹ 1.82 Cr', fillRate:'96.4%', inventoryDoh:'28 d',
    cashCycle:'41 d', otif:'94.2%', revenue:'₹ 38.4 Cr', margin:'22.6%', skus:8, lines:3 },

  // ── products / SKUs ──
  products:[
    { sku:'TPA-4471', name:'Crankshaft Bearing',     cat:'Finished', demand:2840, mape:8.2,  sl:95, shelf:365, abc:'A', xyz:'X', price:1850, cost:1190, line:'LINE-01', cycle:4.2, oee:.84, yield:.97, moq:120 },
    { sku:'TPA-3215', name:'Piston Ring Assembly',   cat:'Finished', demand:4120, mape:11.4, sl:95, shelf:730, abc:'A', xyz:'Y', price:980,  cost:612,  line:'LINE-02', cycle:3.1, oee:.81, yield:.96, moq:200 },
    { sku:'TPA-9904', name:'Valve Seat Insert',      cat:'Finished', demand:1650, mape:6.8,  sl:98, shelf:365, abc:'A', xyz:'X', price:1420, cost:905,  line:'LINE-01', cycle:5.0, oee:.86, yield:.98, moq:80 },
    { sku:'TPA-2188', name:'Connecting Rod',         cat:'Finished', demand:920,  mape:15.1, sl:90, shelf:545, abc:'B', xyz:'Y', price:2240, cost:1510, line:'LINE-03', cycle:6.4, oee:.78, yield:.95, moq:60 },
    { sku:'TPA-5540', name:'Oil Pump Housing',       cat:'Finished', demand:640,  mape:18.7, sl:90, shelf:365, abc:'B', xyz:'Z', price:1680, cost:1140, line:'LINE-02', cycle:4.8, oee:.79, yield:.94, moq:50 },
    { sku:'TPA-7722', name:'Timing Chain Tensioner', cat:'Finished', demand:380,  mape:22.3, sl:85, shelf:180, abc:'C', xyz:'Z', price:2980, cost:2050, line:'LINE-03', cycle:7.2, oee:.74, yield:.92, moq:40 },
    { sku:'RM-STL42', name:'Chromoly Steel Bar 42mm',cat:'Raw',      demand:12400,mape:0,    sl:95, shelf:999, abc:'A', xyz:'X', price:142,  cost:142,  line:'—', cycle:0, oee:0, yield:1, moq:2000 },
    { sku:'RM-BRG18', name:'Bearing Alloy Billet',   cat:'Raw',      demand:8200, mape:0,    sl:95, shelf:999, abc:'A', xyz:'Y', price:228,  cost:228,  line:'—', cycle:0, oee:0, yield:1, moq:1500 },
  ],

  // BOM for selected SKU (TPA-4471) — parts w/ full commercial terms (P5 disclosure)
  bom:[
    { part:'RM-STL42', name:'Chromoly Steel Bar 42mm', qty:0.84, cost:142, lt:14, moq:2000, S:1200, hold:18, shelf:999, sup:'SUP-001' },
    { part:'RM-BRG18', name:'Bearing Alloy Billet',    qty:0.32, cost:228, lt:18, moq:1500, S:900,  hold:22, shelf:999, sup:'SUP-007' },
    { part:'CN-SEAL9', name:'Nitrile Seal Ring',       qty:2.0,  cost:18,  lt:7,  moq:5000, S:140,  hold:12, shelf:540, sup:'SUP-012' },
    { part:'CN-BLT04', name:'Grade 10.9 Bolt M8',      qty:6.0,  cost:4.2, lt:5,  moq:10000,S:60,   hold:9,  shelf:999, sup:'SUP-012' },
    { part:'CN-LUB02', name:'MoS₂ Dry Lubricant',      qty:0.04, cost:340, lt:9,  moq:200,  S:80,   hold:15, shelf:365, sup:'SUP-031' },
  ],

  // MTO order book
  orders:[
    { po:'MTO-9001', cust:'Maruti Suzuki', sku:'TPA-4471', qty:480, due:'2026-06-12', price:1850, status:'firm' },
    { po:'MTO-9002', cust:'TVS Motor',     sku:'TPA-3215', qty:1200,due:'2026-06-20', price:980,  status:'firm' },
    { po:'MTO-9003', cust:'Ashok Leyland', sku:'TPA-2188', qty:220, due:'2026-07-02', price:2240, status:'planned' },
    { po:'MTO-9004', cust:'Bosch India',   sku:'TPA-9904', qty:360, due:'2026-06-28', price:1420, status:'firm' },
    { po:'MTO-9005', cust:'Hyundai Motor', sku:'TPA-4471', qty:300, due:'2026-07-15', price:1850, status:'planned' },
    { po:'MTO-9006', cust:'Tata Motors',   sku:'TPA-5540', qty:180, due:'2026-07-08', price:1680, status:'firm' },
  ],

  // cost events — rolling horizon step-changes
  costEvents:[
    { wk:'W08', item:'RM-STL42', kind:'Price ↑', delta:'+6.5%', reason:'Steel index revision' },
    { wk:'W14', item:'Labor',    kind:'Wage ↑',  delta:'+4.0%', reason:'Annual settlement' },
    { wk:'W22', item:'RM-BRG18', kind:'Price ↓', delta:'-3.2%', reason:'New POSCO contract' },
    { wk:'W31', item:'Power',    kind:'Tariff ↑',delta:'+8.0%', reason:'TANGEDCO revision' },
  ],

  // demand
  history24:[120,135,128,140,155,148,162,170,158,145,138,150,125,140,132,148,160,152,168,175,162,150,142,155],
  forecast12:[148,158,154,165,178,172,186,194,182,168,162,174],
  forecastModels:[
    { name:'HW Multiplicative', mape:6.8, wmape:5.1, bias:-0.4, ts:'2.1', win:true },
    { name:'Auto-SARIMA',       mape:7.2, wmape:5.4, bias:0.2,  ts:'1.8' },
    { name:'LightGBM (ML)',     mape:7.5, wmape:5.6, bias:0.1,  ts:'2.4' },
    { name:'Seasonal LinReg',   mape:8.1, wmape:6.2, bias:1.1,  ts:'3.0' },
    { name:'N-BEATS (DL)',      mape:8.4, wmape:6.4, bias:-0.3, ts:'2.7' },
    { name:'HW Additive',       mape:8.9, wmape:6.8, bias:-0.8, ts:'2.2' },
    { name:'DES (Holt)',        mape:10.4,wmape:7.9, bias:0.5,  ts:'3.4' },
    { name:'Auto-ARIMA',        mape:11.2,wmape:8.4, bias:-1.2, ts:'2.9' },
    { name:'Croston / SBA',     mape:12.6,wmape:9.5, bias:2.1,  ts:'4.1', intermittent:true },
    { name:'TSB (intermittent)',mape:13.1,wmape:9.9, bias:-0.7, ts:'3.8', intermittent:true },
    { name:'Linear Regression', mape:14.3,wmape:10.8,bias:-0.6, ts:'4.5' },
    { name:'SES',               mape:17.2,wmape:13.0,bias:1.4,  ts:'5.2' },
    { name:'WMA(3)',            mape:18.5,wmape:14.2,bias:2.3,  ts:'5.6' },
    { name:'Seasonal Naive',    mape:24.1,wmape:18.2,bias:-4.2, ts:'6.8' },
    { name:'Naive',             mape:28.6,wmape:21.5,bias:5.1,  ts:'7.9' },
  ],
  abcxyz:[ // 3x3 matrix counts
    { abc:'A', X:2, Y:1, Z:0 }, { abc:'B', X:0, Y:1, Z:1 }, { abc:'C', X:0, Y:0, Z:2 },
  ],
  lifecycle:[ // unit demand multiplier over phases
    { ph:'Launch', v:0.3 }, { ph:'Growth', v:0.7 }, { ph:'Maturity', v:1.0 }, { ph:'Decline', v:0.55 },
  ],
  promos:[
    { wk:'W12', sku:'TPA-3215', kind:'OEM rebate', lift:'+18%', units:'+742' },
    { wk:'W26', sku:'TPA-4471', kind:'Festive push', lift:'+11%', units:'+312' },
    { wk:'W40', sku:'TPA-9904', kind:'Contract ramp', lift:'+24%', units:'+396' },
  ],
  consensus:[
    { fn:'Sales',     fc:'14,820', stance:'optimistic' },
    { fn:'Marketing', fc:'13,400', stance:'event-driven' },
    { fn:'Finance',   fc:'12,900', stance:'conservative' },
    { fn:'Ops',       fc:'13,150', stance:'capacity-bound' },
    { fn:'CONSENSUS', fc:'13,400', stance:'committed', em:true },
  ],

  // aggregate plan / S&OP
  aggregate:{
    strategy:'LEVEL', chaseScore:0.34, levelScore:0.81,
    months:[ // capacity vs demand
      { m:'Apr', dem:1180, cap:1240, prod:1200, inv:120 },
      { m:'May', dem:1240, cap:1240, prod:1240, inv:120 },
      { m:'Jun', dem:1420, cap:1240, prod:1300, inv:0 },
      { m:'Jul', dem:1380, cap:1240, prod:1300, inv:-80 },
      { m:'Aug', dem:1120, cap:1240, prod:1240, inv:40 },
      { m:'Sep', dem:1280, cap:1240, prod:1260, inv:20 },
    ],
    workforce:[
      { period:'Q1', base:42, hire:0, fire:0, ot:120 },
      { period:'Q2', base:42, hire:6, fire:0, ot:240 },
      { period:'Q3', base:48, hire:0, fire:0, ot:180 },
      { period:'Q4', base:48, hire:0, fire:4, ot:80 },
    ],
    prebuild:{ detected:true, month:'May', units:480, reason:'Jun demand 1420 > cap 1240' },
  },
  shadow:[
    { res:'Line 1 capacity', dual:1248.40, slack:0,    binding:true },
    { res:'Line 2 capacity', dual:980.20,  slack:0,    binding:true },
    { res:'Line 3 capacity', dual:0,       slack:148,  binding:false },
    { res:'Steel bar stock', dual:42.80,   slack:0,    binding:true },
    { res:'Bearing alloy',   dual:0,       slack:1240, binding:false },
    { res:'Labor hours',     dual:18.60,   slack:0,    binding:true },
  ],

  // production architecture: lines → stages → machines
  lines:[
    { id:'LINE-01', name:'Precision Machining', oee:.84, cap:1240, bottleneck:'Grinding', stages:[
      { id:'ST-FORGE', name:'Forge / Cut', m:3, ct:1.2, oee:.88, cap:1680 },
      { id:'ST-TURN',  name:'CNC Turning', m:4, ct:2.1, oee:.85, cap:1420 },
      { id:'ST-GRIND', name:'Grinding',    m:2, ct:3.4, oee:.82, cap:1240, bottleneck:true },
      { id:'ST-QC1',   name:'CMM Inspect',  m:1, ct:1.8, oee:.90, cap:1560 },
    ]},
    { id:'LINE-02', name:'Ring & Assembly', oee:.81, cap:1980, bottleneck:'Honing', stages:[
      { id:'ST-CAST',  name:'Casting',     m:2, ct:1.6, oee:.83, cap:2200 },
      { id:'ST-HONE',  name:'Honing',      m:3, ct:2.4, oee:.80, cap:1980, bottleneck:true },
      { id:'ST-ASSY',  name:'Assembly',    m:4, ct:1.9, oee:.82, cap:2240 },
      { id:'ST-QC2',   name:'Leak Test',   m:1, ct:1.1, oee:.91, cap:2480 },
    ]},
    { id:'LINE-03', name:'Heavy Components', oee:.78, cap:880, bottleneck:'Heat Treat', stages:[
      { id:'ST-FRG2',  name:'Hot Forge',   m:2, ct:2.8, oee:.79, cap:980 },
      { id:'ST-HEAT',  name:'Heat Treat',  m:1, ct:4.2, oee:.76, cap:880, bottleneck:true },
      { id:'ST-MILL',  name:'5-Axis Mill', m:2, ct:3.6, oee:.80, cap:1020 },
      { id:'ST-QC3',   name:'NDT Inspect', m:1, ct:2.2, oee:.88, cap:1180 },
    ]},
  ],
  mps:[ // weeks of master production schedule, per SKU
    { sku:'TPA-4471', wk:[60,60,72,72,60,48,60,72], atp:[12,8,0,4,16,28,18,6] },
    { sku:'TPA-3215', wk:[90,90,108,108,90,72,90,108], atp:[20,12,0,0,18,30,14,2] },
    { sku:'TPA-9904', wk:[36,36,42,42,36,30,36,42], atp:[8,4,2,0,10,14,8,0] },
    { sku:'TPA-2188', wk:[18,18,24,24,18,12,18,24], atp:[4,2,0,0,6,10,4,0] },
  ],
  changeover:[ // sequence-dependent setup matrix (hrs)
    ['—',1.2,0.8,2.4],[1.0,'—',1.6,2.0],[0.9,1.4,'—',1.8],[2.2,1.9,1.7,'—'],
  ],

  // suppliers
  suppliers:[
    { code:'SUP-001', name:'Bharat Forge Ltd',    loc:'Pune, MH',       lt:14, ltCv:8,  incoterm:'FOR', qty:12400, spend:3124000, risk:'L', otif:96.2 },
    { code:'SUP-007', name:'Mahindra Steel',       loc:'Mumbai, MH',     lt:18, ltCv:12, incoterm:'CIF', qty:8200,  spend:1872000, risk:'L', otif:94.8 },
    { code:'SUP-012', name:'Sundaram Alloys',      loc:'Coimbatore, TN', lt:9,  ltCv:6,  incoterm:'EXW', qty:5600,  spend:1204000, risk:'L', otif:97.5 },
    { code:'SUP-018', name:'Jindal Stainless',     loc:'Raigarh, CG',    lt:22, ltCv:18, incoterm:'FOB', qty:4200,  spend:945000,  risk:'M', otif:89.1 },
    { code:'SUP-024', name:'POSCO Korea (backup)', loc:'Pohang, KR',     lt:42, ltCv:24, incoterm:'CIF', qty:2100,  spend:720000,  risk:'H', otif:82.4 },
    { code:'SUP-031', name:'Kalyani Forge',        loc:'Pune, MH',       lt:16, ltCv:10, incoterm:'FOR', qty:3400,  spend:612000,  risk:'L', otif:93.7 },
  ],
  incoterms:[ // responsibility matrix: who bears cost/risk at each step
    { term:'EXW', export:'B', main:'B', import:'B', risk:'Seller→Buyer at works' },
    { term:'FOB', export:'S', main:'B', import:'B', risk:'Transfers at port rail' },
    { term:'CIF', export:'S', main:'S', import:'B', risk:'Seller pays freight+ins' },
    { term:'FOR', export:'S', main:'S', import:'B', risk:'Free on rail (domestic)' },
    { term:'DDP', export:'S', main:'S', import:'S', risk:'Seller bears everything' },
  ],
  landedCost:{ item:'Bearing Alloy Billet · POSCO Korea', rows:[
    { k:'FOB Price (USD)',v:28500,c:'USD' },{ k:'FX @ ₹84.20/$',v:2399700,c:'INR' },
    { k:'Ocean Freight',v:124000,c:'INR' },{ k:'Insurance @ 0.5%',v:11998,c:'INR' },
    { k:'CIF Value',v:2535698,c:'INR',em:true },{ k:'Basic Customs Duty 7.5%',v:190177,c:'INR' },
    { k:'Social Welfare 10%',v:19018,c:'INR' },{ k:'IGST 18% (ITC)',v:494924,c:'INR',sub:true },
    { k:'Clearing · CHA',v:28000,c:'INR' },{ k:'Inland to Plant',v:42000,c:'INR' },
    { k:'LANDED COST',v:2814891,c:'INR',total:true },
  ]},
  otifLedger:[
    { po:'PO-4471-22', sup:'SUP-001', due:'W18', got:'W18', otif:'✓', qty:'2000/2000' },
    { po:'PO-3215-09', sup:'SUP-007', due:'W16', got:'W17', otif:'late', qty:'1500/1500' },
    { po:'PO-9904-31', sup:'SUP-018', due:'W14', got:'W14', otif:'short', qty:'1800/2000' },
    { po:'PO-2188-12', sup:'SUP-024', due:'W20', got:'W22', otif:'late', qty:'2100/2100' },
  ],

  // logistics
  nodes:[
    { id:'PLANT-CHN', type:'Plant',    name:'Chennai Plant',    lat:13.08, lng:80.27, cap:'—' },
    { id:'WH-CHN',    type:'WH',       name:'Sriperumbudur WH', lat:12.96, lng:79.94, cap:'8,200 m³' },
    { id:'DC-BLR',    type:'DC',       name:'Bengaluru DC',     lat:12.97, lng:77.59, cap:'3,400 m³' },
    { id:'DC-PUN',    type:'DC',       name:'Pune DC',          lat:18.52, lng:73.86, cap:'2,800 m³' },
    { id:'CUST-GGN',  type:'Customer', name:'Gurgaon Cluster',  lat:28.46, lng:77.03, cap:'—' },
  ],
  lanes:[
    { from:'PLANT-CHN', to:'WH-CHN',  mode:'FTL', km:42,   rate:18,  lt:0.2 },
    { from:'WH-CHN',    to:'DC-BLR',  mode:'FTL', km:346,  rate:14,  lt:1.0 },
    { from:'WH-CHN',    to:'DC-PUN',  mode:'Rail',km:1180, rate:6.2, lt:3.0 },
    { from:'DC-PUN',    to:'CUST-GGN',mode:'LTL', km:1420, rate:22,  lt:2.5 },
    { from:'DC-BLR',    to:'CUST-GGN',mode:'Air', km:1740, rate:88,  lt:0.5 },
  ],
  tpl:[
    { code:'3PL-BLR', name:'BlueDart Surface', mode:'LTL', sla:'98.1%', rate:'₹22/kg', zones:'PAN-IN' },
    { code:'3PL-VRL', name:'VRL Logistics',    mode:'FTL', sla:'96.4%', rate:'₹14/km', zones:'South+West' },
    { code:'3PL-CON', name:'CONCOR Rail',      mode:'Rail',sla:'94.0%', rate:'₹6.2/km',zones:'Trunk' },
  ],
  cog:{ lat:15.2, lng:78.4, label:'Optimal hub ~ Kurnool, AP', saving:'₹ 28.4 L/yr vs current' },

  // finance
  financeSubtabs:[
    { id:'cashflow', n:'a', label:'Cash Flow', count:4 },
    { id:'capital',  n:'b', label:'Capital',   count:5 },
    { id:'decisions',n:'c', label:'Capital Decisions', count:6 },
    { id:'assets',   n:'d', label:'Assets',    count:2 },
    { id:'bvl',      n:'e', label:'Buy vs Lease', count:1 },
    { id:'cac',      n:'f', label:'CAC',       count:1 },
    { id:'fx',       n:'g', label:'FX & Hedge',count:2 },
  ],
  npv:[
    { y:'Y0', cf:-22000000, dcf:-22000000 },
    { y:'Y1', cf:6800000,   dcf:6105000 },
    { y:'Y2', cf:8400000,   dcf:6772000 },
    { y:'Y3', cf:9200000,   dcf:6658000 },
    { y:'Y4', cf:9800000,   dcf:6368000 },
    { y:'Y5', cf:10400000,  dcf:6066000 },
  ],
  wacc:{ rate:11.40, ke:14.2, kd:8.6, taxShield:25.17, eWeight:62, dWeight:38, beta:1.18, rf:7.1, erp:6.0 },
  cashflow:[ // monthly working capital
    { m:'Apr', ar:8.2, ap:5.4, inv:6.1, net:8.9 },
    { m:'May', ar:8.6, ap:5.8, inv:6.4, net:9.2 },
    { m:'Jun', ar:9.4, ap:6.2, inv:7.0, net:10.2 },
    { m:'Jul', ar:9.1, ap:6.0, inv:6.8, net:9.9 },
    { m:'Aug', ar:7.8, ap:5.2, inv:5.9, net:8.5 },
    { m:'Sep', ar:8.4, ap:5.6, inv:6.3, net:9.1 },
  ],
  assets:[
    { id:'CNC-01', name:'DMG Mori CNC Lathe', cost:8400000, life:10, age:3, wdv:5880000, dep:840000 },
    { id:'GRD-01', name:'Studer Grinder',     cost:6200000, life:12, age:2, wdv:5167000, dep:516667 },
    { id:'HT-01',  name:'Vacuum Heat Furnace',cost:5400000, life:15, age:4, wdv:3960000, dep:360000 },
    { id:'CMM-01', name:'Zeiss CMM',          cost:3800000, life:8,  age:1, wdv:3325000, dep:475000 },
  ],
  cac:{ blended:4280, payback:'2.4 mo', ltv:184000, ltvcac:43, channels:[
    { ch:'OEM Direct', cac:2100, share:64 },
    { ch:'Tier-1 Ref', cac:3800, share:24 },
    { ch:'Trade Show', cac:9400, share:12 },
  ]},
  fxHedge:[
    { exp:'POSCO USD payable', amt:'$28.5K', due:'W20', hedge:'Forward @ 84.60', cover:'80%' },
    { exp:'Steel import EUR',  amt:'€12.0K', due:'W26', hedge:'Unhedged', cover:'0%' },
    { exp:'Export receivable', amt:'$44.0K', due:'W30', hedge:'Option collar', cover:'60%' },
  ],

  // ── console / solvers (Cartesian map) ──
  // x = horizon (operational→strategic), y = decision domain
  solvers:[
    { id:'profit',    name:'Profit Mix',     engine:'LP',   x:0.18, y:0.82, t:0.42, obj:'₹6.84 Cr', status:'done',    feeds:['procure','produce'] },
    { id:'procure',   name:'Procurement',    engine:'MILP', x:0.34, y:0.46, t:2.18, obj:'₹3.12 Cr', status:'running', feeds:['produce'] },
    { id:'produce',   name:'Production',     engine:'MILP', x:0.42, y:0.20, t:1.84, obj:'₹42 L',     status:'queued',  feeds:['transport'] },
    { id:'transport', name:'Transport',      engine:'MILP', x:0.62, y:0.30, t:0.0,  obj:'—',         status:'queued',  feeds:[] },
    { id:'montecarlo',name:'Monte Carlo',    engine:'SIM',  x:0.72, y:0.62, t:0.0,  obj:'—',         status:'idle',    feeds:[] },
    { id:'capital',   name:'Capital Budget', engine:'MILP', x:0.86, y:0.82, t:0.0,  obj:'—',         status:'idle',    feeds:[] },
    { id:'sop',       name:'Closed-Loop S&OP',engine:'LP',  x:0.56, y:0.78, t:0.0,  obj:'—',         status:'idle',    feeds:['profit'] },
  ],
  solverModes:[
    { id:'procure', label:'Procurement MILP', sel:true },
    { id:'produce', label:'Production MILP' },
    { id:'profit',  label:'Profit Maximizer LP' },
    { id:'transport',label:'Transport MILP' },
    { id:'montecarlo',label:'Monte Carlo' },
    { id:'capital', label:'Capital Budget' },
    { id:'sop',     label:'Closed-Loop S&OP' },
    { id:'pipeline',label:'Full Pipeline' },
    { id:'rolling', label:'Rolling-Horizon' },
  ],
  constraints:[
    { id:'budget', label:'Budget envelope',   on:true },
    { id:'capacity',label:'Line capacity',    on:true },
    { id:'moq',    label:'Supplier MOQ',      on:true },
    { id:'safety', label:'Safety stock',      on:true },
    { id:'shelf',  label:'Shelf-life expiry', on:false },
    { id:'incoterm',label:'Incoterm terms',   on:false },
  ],
  consoleResults:{ // result sub-tab section inventories
    procurement:['Procurement MILP Results','Multi-Echelon Inventory','PO Register','RM Timeline','Reorder Policy (s,S)/(R,Q)','Regime-Aware Sourcing','MRP Explosion'],
    production:['Production Schedule','Sequence-Dependent Changeover','Production Order Register','Product Fulfillment','Shutdown Candidates','Line-Level Execution','Line×Period Matrix','Gantt','MPS','Order Promising (ATP/CTP)','Capacity Conflict Check'],
    profit:['Profit Maximizer Results','Reconciled Mix','Shadow Prices'],
    transport:['Transport Results','Lane Allocation','Consolidation Plan'],
    risk:['Monte Carlo Results','CVaR Frontier','Fragility Index'],
    capital:['Capital Budget Results','Endogenous Capacity Plan','Per-Line CapEx'],
    sop:['Closed-loop S&OP','Reconciled Mix','Pipeline (3 steps)'],
    pipeline:['Profit → Procure → Produce','Wave Comparison','Final-Wave PO Register'],
    rolling:['Rolling-Horizon MPS','Wave Comparison','MILP Export'],
  },
  poRegister:[
    { po:'PO-001', part:'RM-STL42', sup:'SUP-001', qty:2400, wk:'W08', val:340800, mode:'FOR' },
    { po:'PO-002', part:'RM-BRG18', sup:'SUP-007', qty:1500, wk:'W09', val:342000, mode:'CIF' },
    { po:'PO-003', part:'CN-SEAL9', sup:'SUP-012', qty:6000, wk:'W08', val:108000, mode:'EXW' },
    { po:'PO-004', part:'RM-STL42', sup:'SUP-001', qty:2000, wk:'W12', val:284000, mode:'FOR' },
    { po:'PO-005', part:'CN-LUB02', sup:'SUP-031', qty:200,  wk:'W10', val:68000,  mode:'FOR' },
  ],
  gantt:[
    { line:'LINE-01', jobs:[{sku:'TPA-4471',s:0,d:6,util:.88},{sku:'TPA-2188',s:6,d:3,util:.72},{sku:'TPA-9904',s:9,d:5,util:.91},{sku:'TPA-4471',s:14,d:4,util:.85}]},
    { line:'LINE-02', jobs:[{sku:'TPA-3215',s:0,d:8,util:.94},{sku:'TPA-5540',s:8,d:3,util:.68},{sku:'TPA-3215',s:11,d:7,util:.92}]},
    { line:'LINE-03', jobs:[{sku:'TPA-7722',s:1,d:3,util:.55},{sku:'TPA-9904',s:4,d:4,util:.82},{sku:'TPA-2188',s:8,d:5,util:.76},{sku:'TPA-7722',s:13,d:2,util:.61},{sku:'TPA-5540',s:15,d:3,util:.70}]},
  ],

  // scenarios
  scenarioSubtabs:[
    { id:'risk', n:'a', label:'Risk', count:7 },
    { id:'cost', n:'b', label:'Cost', count:4 },
    { id:'perf', n:'c', label:'Performance', count:3 },
    { id:'explore', n:'d', label:'Explore', count:6 },
  ],
  controlTower:[
    { sev:'H', area:'Supply',  msg:'POSCO LT slipped to 44d (+2)', kpi:'Procure', t:'12m ago' },
    { sev:'M', area:'Demand',  msg:'TPA-7722 tracking signal > 4σ', kpi:'Forecast', t:'1h ago' },
    { sev:'M', area:'Capacity',msg:'Line-03 Heat Treat at 96% util', kpi:'Produce', t:'2h ago' },
    { sev:'L', area:'Finance', msg:'WC tied-up ₹3.8Cr near cap',     kpi:'Cash', t:'4h ago' },
  ],
  mcBuckets:[ {x:420,n:12},{x:430,n:28},{x:440,n:52},{x:450,n:88},{x:460,n:124},{x:470,n:162},{x:480,n:178},{x:490,n:148},{x:500,n:102},{x:510,n:58},{x:520,n:28},{x:530,n:14},{x:540,n:6} ],
  mcStats:{ mean:478.4, median:476.2, p5:432.1, p95:518.7, var95:518.7, cvar95:528.4, fragility:0.073 },
  tornado:[
    { param:'Material cost (±15%)', low:-18.4, high:21.2 },
    { param:'Demand volatility',    low:-12.1, high:15.8 },
    { param:'Lead time (supplier)', low:-8.2,  high:11.6 },
    { param:'Service level 90↔99%', low:-6.4,  high:9.1 },
    { param:'Capacity (OEE)',       low:-5.8,  high:7.2 },
    { param:'Setup cost',           low:-3.1,  high:4.4 },
    { param:'FX USD-INR',           low:-2.6,  high:3.8 },
  ],
  tco:[
    { sku:'TPA-4471', unit:1190, hold:84, order:42, quality:28, obsol:12, tco:1356 },
    { sku:'TPA-3215', unit:612,  hold:48, order:31, quality:18, obsol:8,  tco:717 },
    { sku:'TPA-2188', unit:1510, hold:108,order:58, quality:42, obsol:22, tco:1740 },
  ],
  evm:{ pv:8400000, ev:7980000, ac:8260000, spi:0.95, cpi:0.97, eac:13030000, bac:12640000 },
  costWaterfall:[
    { k:'Material', v:7.8 },{ k:'Labour', v:2.1 },{ k:'Overhead', v:1.4 },
    { k:'Logistics', v:0.8 },{ k:'Finance', v:0.5 },{ k:'TOTAL', v:12.64, total:true },
  ],
  disruptions:[
    { id:'DR-01', event:'Port congestion · Chennai', prob:'Med', impact:'₹18L', mitig:'Air bridge backup' },
    { id:'DR-02', event:'POSCO export quota',         prob:'Low', impact:'₹42L', mitig:'Dual-source Jindal' },
    { id:'DR-03', event:'Monsoon road closure',       prob:'High',impact:'₹8L',  mitig:'Pre-position WH-CHN' },
  ],
  riskMatrix:[ // prob × impact heat
    { p:'High', cells:[1,2,3] }, { p:'Med', cells:[1,3,2] }, { p:'Low', cells:[2,1,1] },
  ],
  stakeholders:[
    { name:'Plant Head',   power:'H', interest:'H', q:'Manage closely' },
    { name:'CFO',          power:'H', interest:'M', q:'Keep satisfied' },
    { name:'OEM Customer', power:'H', interest:'H', q:'Manage closely' },
    { name:'Suppliers',    power:'M', interest:'H', q:'Keep informed' },
    { name:'Shop floor',   power:'L', interest:'H', q:'Keep informed' },
    { name:'Auditors',     power:'M', interest:'L', q:'Monitor' },
  ],
  whatif:['Material cost up 20% for Q3','Demand doubles for TPA-4471 in Dec','POSCO lead time +2 weeks','Capacity down 30% on Line 2','Rupee falls to ₹86.50/$','New supplier with LT=2w'],
  sop:{ volumeGap:4.2, revGap:-1.8, marginGap:2.1, inventoryGap:-6.4 },
  cascade:[ // parameter cascade chain
    'WACC 11.4%','→ Discount factor','→ NPV ₹13.7L','→ CapEx gate','→ Line-03 approved',
  ],
  versions:[
    { v:'v3.2.1', t:'30 May 14:32', who:'planner', note:'Solved procurement wave 2' },
    { v:'v3.2.0', t:'30 May 11:08', who:'planner', note:'Updated POSCO lead time' },
    { v:'v3.1.4', t:'29 May 17:44', who:'admin',   note:'New industry preset' },
  ],

  // reference
  learnSections:['EOQ · Economic Order Quantity','Safety Stock · z-score','ROP · Reorder Point','ABC/XYZ Classification','MILP Basics','Shadow Prices Intuition','Monte Carlo · LLN','Bullwhip Effect','CCC · Cash Cycle','WACC & NPV','Little\u2019s Law','Newsvendor Model','(s,S) Policy','Level vs Chase','OEE Decomposition','Incoterms 2020','CVaR & Fragility','Croston Intermittent','Disaggregation','Tracking Signal','Sequence Changeover'],
  sapTcodes:[
    { code:'MD01', name:'MRP Run',           area:'Planning' },
    { code:'MD04', name:'Stock/Req List',    area:'Planning' },
    { code:'CO01', name:'Production Order',   area:'Production' },
    { code:'ME21N',name:'Create PO',         area:'Procurement' },
    { code:'MIGO', name:'Goods Movement',     area:'Inventory' },
    { code:'VA01', name:'Sales Order',        area:'Sales' },
    { code:'MM01', name:'Material Master',     area:'Master Data' },
    { code:'CK11N',name:'Cost Estimate',      area:'Costing' },
  ],
  holidays:[['Jan 15','Pongal'],['Jan 26','Republic Day'],['Mar 14','Shivaratri'],['Apr 10','Good Friday'],['Apr 14','Tamil New Year'],['May 01','Labour Day'],['Aug 15','Independence Day'],['Sep 02','Vinayagar Chaturthi'],['Oct 02','Gandhi Jayanti'],['Oct 20','Dussehra'],['Nov 08','Deepavali'],['Dec 25','Christmas']],
  readiness:[
    { solver:'Profit Mix',   inputs:['Demand fc','Prices','Capacity'], ready:true },
    { solver:'Procurement',  inputs:['BOM','Suppliers','Budget'],      ready:true },
    { solver:'Production',   inputs:['MPS','Lines','Changeover'],      ready:true },
    { solver:'Transport',    inputs:['Nodes','Lanes','3PL'],           ready:false },
    { solver:'Monte Carlo',  inputs:['Distributions','Runs'],          ready:false },
    { solver:'Capital',      inputs:['Assets','WACC','Cash flow'],     ready:true },
    { solver:'S&OP',         inputs:['Aggregate','Consensus'],         ready:true },
  ],
};
window.M = M;
window.MOCK = M;
