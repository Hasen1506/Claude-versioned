// ════════════════════════════════════════════════════════════════════════
// data.jsx — Tata Precision Auto Components dataset (extended for all stages)
// One mock store. Real-ish figures, INR, TN automotive context.
// ════════════════════════════════════════════════════════════════════════
const M = {
  company:'Tata Precision Auto Components Pvt. Ltd.',
  short:'TPAC', city:'Chennai, TN', currency:'₹', fy:'FY 26-27',
  updated:'30 May 2026 · 14:32 IST', cin:'U34300TN2018PTC124589', gstin:'33AAACT2727Q1ZV',

  // ── top-level nav: Home + workflow stages, re-sequenced into the v2 spine ──
  // DEFINE → PLAN → DECIDE/MONITOR, dependency-ordered (handoff v2 Part 2).
  stages:[
    { id:'home',       n:'00', name:'Home',        band:'',        sub:'KPIs · solver network · control tower' },
    { id:'setup',      n:'01', name:'Setup',       band:'DEFINE',  sub:'Identity · calendar' },
    { id:'products',   n:'02', name:'Products',    band:'DEFINE',  sub:'Define · BOM · costs' },
    { id:'network',    n:'03', name:'Network',     band:'DEFINE',  sub:'Nodes · lanes · contracts · on-hand' },
    { id:'demand',     n:'04', name:'Demand',      band:'PLAN',    sub:'History · forecast · ABC/XYZ' },
    { id:'plan',       n:'05', name:'Plan',        band:'PLAN',    sub:'S&OP · level-vs-chase · duals' },
    { id:'production', n:'06', name:'Production',   band:'PLAN',    sub:'Lines · MPS(day) · ATP/CTP' },
    { id:'sourcing',   n:'07', name:'Sourcing',    band:'PLAN',    sub:'MRP · POs · landed · OTIF' },
    { id:'logistics',  n:'08', name:'Logistics',   band:'PLAN',    sub:'Transport · allocation · CoG' },
    { id:'finance',    n:'09', name:'Finance',     band:'DECIDE',  sub:'Cash · capital · invest · FX' },
    { id:'console',    n:'10', name:'Console',     band:'DECIDE',  sub:'16 engines · run any solver' },
    { id:'scenarios',  n:'11', name:'Scenarios',   band:'DECIDE',  sub:'Risk · cost · what-if' },
    // Reference demoted (app_v2): no longer a planning stage — reached via the
    // masthead "Learn" button. Still registered in main.jsx so it renders when active.
  ],

  // (R13) M.pipeline removed — the ribbon (chrome.jsx) now derives its 6 stages
  // live from the LOOP_STEPS solve cache, not a hardcoded status/val seed.

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

  // MN-A · real multi-product BOM — which finished SKU actually consumes which part,
  // and in what qty/unit. Replaces the "every FG uses every part" illustrative single
  // BOM: each part is now shared by a real SUBSET of the portfolio, so the W8 pooling
  // cohort (and its dividend) is exact rather than all-6-FG. qty_per is the part units
  // per 1 finished unit of that SKU.
  skuBom:{
    'TPA-4471':[{part:'RM-STL42',qty:0.90},{part:'RM-BRG18',qty:1.00},{part:'CN-SEAL9',qty:2.0},{part:'CN-LUB02',qty:0.05}],
    'TPA-3215':[{part:'RM-STL42',qty:0.55},{part:'CN-SEAL9',qty:3.0},{part:'CN-BLT04',qty:8.0}],
    'TPA-9904':[{part:'RM-BRG18',qty:0.60},{part:'CN-LUB02',qty:0.03}],
    'TPA-2188':[{part:'RM-STL42',qty:1.40},{part:'RM-BRG18',qty:0.50},{part:'CN-BLT04',qty:6.0}],
    'TPA-5540':[{part:'RM-STL42',qty:1.10},{part:'CN-SEAL9',qty:1.0},{part:'CN-BLT04',qty:4.0},{part:'CN-LUB02',qty:0.04}],
    'TPA-7722':[{part:'RM-BRG18',qty:0.40},{part:'CN-SEAL9',qty:2.0},{part:'CN-BLT04',qty:10.0}],
  },

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

  // logistics / network (handoff v2 §1.4 — per-item, directional)
  nodes:[
    { id:'PLANT-CHN', type:'plant',    name:'Chennai Plant',    lat:13.08, lng:80.27, capacityUom:'u/mo',  capacity:4360, cap:'4,360 u/mo' },
    { id:'WH-CHN',    type:'wh',       name:'Sriperumbudur WH', lat:12.96, lng:79.94, capacityUom:'m³',    capacity:8200, cap:'8,200 m³' },
    { id:'DC-BLR',    type:'dc',       name:'Bengaluru DC',     lat:12.97, lng:77.59, capacityUom:'m³',    capacity:3400, cap:'3,400 m³' },
    { id:'DC-PUN',    type:'dc',       name:'Pune DC',          lat:18.52, lng:73.86, capacityUom:'m³',    capacity:2800, cap:'2,800 m³' },
    { id:'CUST-GGN',  type:'customer', name:'Gurgaon Cluster',  lat:28.46, lng:77.03, capacityUom:'—',     capacity:0,    cap:'—' },
    { id:'SUP-001',   type:'supplier', name:'Bharat Forge',     lat:18.52, lng:73.86, capacityUom:'—',     capacity:0,    cap:'—' },
    { id:'SUP-007',   type:'supplier', name:'Mahindra Steel',   lat:19.07, lng:72.87, capacityUom:'—',     capacity:0,    cap:'—' },
    { id:'SUP-012',   type:'supplier', name:'Sundaram Alloys',  lat:11.01, lng:76.96, capacityUom:'—',     capacity:0,    cap:'—' },
  ],
  // each lane carries ONE item in ONE direction (inbound part / outbound FG)
  lanes:[
    { id:'L-IN-1',  from:'SUP-001', to:'PLANT-CHN', direction:'inbound',  item:'RM-STL42', mode:'FOR',  km:1180, rate:18,  lt:14,  leadDays:14,  contractId:'C-STL' },
    { id:'L-IN-2',  from:'SUP-007', to:'PLANT-CHN', direction:'inbound',  item:'RM-BRG18', mode:'CIF',  km:1330, rate:22,  lt:18,  leadDays:18,  contractId:'C-BRG' },
    { id:'L-IN-3',  from:'SUP-012', to:'PLANT-CHN', direction:'inbound',  item:'CN-SEAL9', mode:'EXW',  km:510,  rate:9,   lt:7,   leadDays:7,   contractId:'C-SEAL' },
    { id:'L-OUT-1', from:'PLANT-CHN', to:'WH-CHN',  direction:'outbound', item:'TPA-4471', mode:'FTL',  km:42,   rate:18,  lt:0.2, leadDays:0.2, contractId:'C-FTL' },
    { id:'L-OUT-2', from:'WH-CHN',   to:'DC-BLR',   direction:'outbound', item:'TPA-4471', mode:'FTL',  km:346,  rate:14,  lt:1.0, leadDays:1,   contractId:'C-FTL' },
    { id:'L-OUT-3', from:'WH-CHN',   to:'DC-PUN',   direction:'outbound', item:'TPA-4471', mode:'Rail', km:1180, rate:6.2, lt:3.0, leadDays:3,   contractId:'C-RAIL' },
    { id:'L-OUT-4', from:'DC-PUN',   to:'CUST-GGN', direction:'outbound', item:'TPA-4471', mode:'LTL',  km:1420, rate:22,  lt:2.5, leadDays:2.5, contractId:'C-LTL' },
    { id:'L-OUT-5', from:'DC-BLR',   to:'CUST-GGN', direction:'outbound', item:'TPA-4471', mode:'Air',  km:1740, rate:88,  lt:0.5, leadDays:0.5, contractId:'C-AIR' },
  ],
  // time-varying contracts: rateByPeriod = [[periodId, price], …]
  contracts:[
    { id:'C-STL',  type:'fixed',       party:'SUP-001', item:'RM-STL42', rateByPeriod:[[0,142],[6,151],[40,151]] },
    { id:'C-BRG',  type:'take-or-pay', party:'SUP-007', item:'RM-BRG18', rateByPeriod:[[0,228],[20,221],[40,221]] },
    { id:'C-SEAL', type:'spot',        party:'SUP-012', item:'CN-SEAL9', rateByPeriod:[[0,18],[20,19],[40,18]] },
    { id:'C-FTL',  type:'volume',      party:'VRL',     item:'—',        rateByPeriod:[[0,14],[26,13.4]] },
  ],
  // opening on-hand as an item × location matrix (only meaningful post-Products)
  onHand:[
    { item:'RM-STL42', loc:'PLANT-CHN', qty:4200, uom:'kg' },
    { item:'RM-BRG18', loc:'PLANT-CHN', qty:1800, uom:'kg' },
    { item:'CN-SEAL9', loc:'PLANT-CHN', qty:6200, uom:'u' },
    { item:'TPA-4471', loc:'WH-CHN',    qty:340,  uom:'u' },
    { item:'TPA-4471', loc:'DC-BLR',    qty:120,  uom:'u' },
    { item:'TPA-3215', loc:'DC-BLR',    qty:620,  uom:'u' },
    { item:'TPA-9904', loc:'DC-PUN',    qty:180,  uom:'u' },
  ],
  tpl:[
    { code:'3PL-BLR', name:'BlueDart Surface', mode:'LTL', sla:'98.1%', rate:'₹22/kg', zones:'PAN-IN' },
    { code:'3PL-VRL', name:'VRL Logistics',    mode:'FTL', sla:'96.4%', rate:'₹14/km', zones:'South+West' },
    { code:'3PL-CON', name:'CONCOR Rail',      mode:'Rail',sla:'94.0%', rate:'₹6.2/km',zones:'Trunk' },
  ],
  cog:{ lat:15.2, lng:78.4, label:'Optimal hub ~ Kurnool, AP', saving:'₹ 28.4 L/yr vs current' },

  // finance — P3 sub-tabs regrouped 7→5 by finance question (app_v2). EVM + CCC
  // pulled in from Scenarios; Buy-vs-Lease folded into Investments; CAC demoted
  // behind Advanced inside Cash & WC.
  financeSubtabs:[
    { id:'cash',    n:'a', label:'Cash & WC',   count:6 },
    { id:'capital', n:'b', label:'Capital',     count:6 },
    { id:'value',   n:'c', label:'Value (EVA)', count:3 },
    { id:'invest',  n:'d', label:'Investments', count:4 },
    { id:'assets',  n:'e', label:'Assets',      count:2 },
    { id:'fx',      n:'f', label:'FX & Hedging',count:3 },
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

  // ── the REAL solver inventory (handoff v2 §1.3): 16 engines in 5 families ──
  // drawn ONCE by <SolverNetwork/>, shared by Home + Console.
  solverFamilies:[
    { id:'forecast', name:'Forecast',   kind:'statistical / ML',   accent:'a2' },
    { id:'plan',     name:'Plan · S&OP', kind:'LP (closed-loop)',    accent:'a3' },
    { id:'optimize', name:'Optimize',    kind:'LP / MILP',          accent:'ink' },
    { id:'risk',     name:'Risk',        kind:'simulation / robust', accent:'a4' },
    { id:'capital',  name:'Capital',     kind:'LP / MILP',          accent:'gn' },
  ],
  solvers:[
    { id:'forecast',         name:'Forecast',        fam:'forecast', engine:'HW·ARIMA·ML·DL·Croston', status:'done',    obj:'MAPE 6.8%',  go:'demand' },
    { id:'aggregate',        name:'Aggregate',       fam:'plan',     engine:'LP',          status:'done',    obj:'Level mix',  go:'plan' },
    { id:'disaggregate',     name:'Disaggregate',    fam:'plan',     engine:'LP',          status:'done',    obj:'5 SKUs',     go:'plan' },
    { id:'reconcile',        name:'Reconcile',       fam:'plan',     engine:'closed-loop', status:'done',    obj:'gap 2.1%',   go:'plan' },
    { id:'profitmix',        name:'Profit Mix',      fam:'optimize', engine:'LP',          status:'done',    obj:'₹6.84 Cr',   go:'console' },
    { id:'procurement',      name:'Procurement',     fam:'optimize', engine:'MILP',        status:'running', obj:'₹3.12 Cr',   go:'console' },
    { id:'production',        name:'Production',      fam:'optimize', engine:'MILP',        status:'queued',  obj:'₹42 L',      go:'console' },
    { id:'sequencing',       name:'Sequencing',      fam:'optimize', engine:'ATSP heuristic',status:'queued',  obj:'−18% setup',  go:'production' },
    { id:'lotsizing',        name:'Lot Sizing',      fam:'optimize', engine:'closed-form / DP',status:'idle',  obj:'EOQ / WW',   go:'console' },
    { id:'transport',        name:'Transport',       fam:'optimize', engine:'LP',          status:'queued',  obj:'₹24.8 L',    go:'logistics' },
    { id:'allocation',       name:'Allocation',      fam:'optimize', engine:'LP',          status:'idle',    obj:'DC→cust',    go:'logistics' },
    { id:'consolidate',      name:'Consolidate',     fam:'optimize', engine:'heuristic',   status:'idle',    obj:'₹3.2 L',     go:'logistics' },
    { id:'montecarlo',       name:'Monte Carlo',     fam:'risk',     engine:'SIM',         status:'idle',    obj:'1,000 runs', go:'scenarios' },
    { id:'cvar',             name:'CVaR',            fam:'risk',     engine:'stochastic LP',status:'idle',    obj:'₹528 L',     go:'scenarios' },
    { id:'capital',          name:'Capital',         fam:'capital',  engine:'LP',          status:'idle',    obj:'NPV +₹24L',  go:'finance' },
    { id:'capital_capacity', name:'Capital Capacity',fam:'capital',  engine:'MILP',        status:'idle',    obj:'+38% cap',   go:'finance' },
  ],
  // real /api/solve hand-offs (data dependencies) drawn as edges
  solverEdges:[
    ['forecast','aggregate'],['aggregate','disaggregate'],['disaggregate','reconcile'],
    ['reconcile','profitmix'],['profitmix','reconcile'],
    ['profitmix','procurement'],['procurement','production'],['production','sequencing'],
    ['production','lotsizing'],['sequencing','transport'],['transport','allocation'],['transport','consolidate'],
    ['reconcile','capital'],['capital','capital_capacity'],['montecarlo','cvar'],
  ],
  // orchestration chains (the run-console can invoke these meta-pipelines)
  solverOrchestration:[
    { id:'pipeline', label:'Full Pipeline', note:'forecast→…→transport' },
    { id:'rolling',  label:'Rolling-Horizon', note:'re-solve each bucket' },
    { id:'sop',      label:'Closed-Loop S&OP', note:'reconcile ⇄ profit' },
  ],
  solverModes:[
    { id:'procurement', label:'Procurement MILP', sel:true },
    { id:'production',  label:'Production MILP' },
    { id:'profitmix',   label:'Profit Maximizer LP' },
    { id:'transport',   label:'Transport LP' },
    { id:'montecarlo',  label:'Monte Carlo SIM' },
    { id:'capital',     label:'Capital Budget LP' },
    { id:'sop',         label:'Closed-Loop S&OP' },
    { id:'pipeline',    label:'Full Pipeline' },
    { id:'rolling',     label:'Rolling-Horizon' },
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
  // app_v2: 'Performance' dissolved — its cards were misfiled. EVM + CCC → Finance;
  // S&OP Gap → Plan; FVA → Demand; KPI Dashboard cut (dup of Home); Version
  // History → masthead. Risk · Cost · Explore are the real three.
  scenarioSubtabs:[
    { id:'scenarios', n:'a', label:'What-if', count:1 },
    { id:'risk',      n:'b', label:'Risk & Stress', count:4 },
    { id:'loop',      n:'c', label:'Loop', count:1 },
    { id:'cost',      n:'d', label:'Cost', count:2 },
    { id:'explore',   n:'e', label:'Explore', count:2 },
  ],
  // (R13) controlTower seed removed — Home's exception inbox derives live alerts
  // from real state (stale solves · breach triggers · MC tail) via liveAlerts().
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
// ════════════════════════════════════════════════════════════════════════
// PART 1 — the global data model (handoff v2): item identity + period axis.
// Built here, AFTER M, so it can derive from products/bom. Everything
// time-bound stores a period id and renders periods[id].label (a real date).
// ════════════════════════════════════════════════════════════════════════
const _MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function _isoWeek(d){
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - day + 3);
  const first = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((t - first) / 86400000 - 3 + ((first.getUTCDay() + 6) % 7)) / 7);
}
// buildPeriods(calendar) → [{ id, label, date, iso }]  (one axis the app renders against)
function buildPeriods(cal){
  const start = new Date(cal.start + 'T00:00:00');
  const step = cal.grain === 'day' ? 1 : cal.grain === 'week' ? 7 : 30;
  return Array.from({ length: cal.count }, (_, i) => {
    const d = new Date(start); d.setDate(start.getDate() + i * step);
    const date = String(d.getDate()).padStart(2,'0') + ' ' + _MONTHS[d.getMonth()];
    const label = cal.grain === 'week'  ? 'W' + String(_isoWeek(d)).padStart(2,'0')
                : cal.grain === 'month' ? _MONTHS[d.getMonth()] + ' ' + String(d.getFullYear()).slice(2)
                : date;
    return { id:i, label, date, iso:d.toISOString().slice(0,10) };
  });
}
M.calendar = { grain:'week', start:'2026-06-01', count:52 };
M.periods  = buildPeriods(M.calendar);
// productionWorkDays(weekIso, n) → up to n REAL working dates in the ISO week
// starting weekIso, excluding Sundays and Indian holidays (M.holidays, 'MMM DD').
// The MPS day-drill spreads each week's SOLVED quantity across exactly these
// dates — never a synthetic per-day split. (W3 · PR-2 calendar-aware MPS.)
function productionWorkDays(weekIso, n){
  const start = new Date(weekIso + 'T00:00:00');
  const hol = new Set((M.holidays || []).map(h=>h[0]));   // 'MMM DD'
  const out = [];
  for(let i=0; i<7 && out.length < (n || 6); i++){
    const d = new Date(start); d.setDate(start.getDate() + i);
    if(d.getDay() === 0) continue;                          // Sunday off
    const tag = _MONTHS[d.getMonth()] + ' ' + String(d.getDate()).padStart(2,'0');
    if(hol.has(tag)) continue;                              // Indian holiday off
    out.push({ iso:d.toISOString().slice(0,10),
      label:String(d.getDate()).padStart(2,'0') + ' ' + _MONTHS[d.getMonth()],
      dow:['Su','Mo','Tu','We','Th','Fr','Sa'][d.getDay()] });
  }
  return out;
}
M.pLabel   = (pid)=> (M.periods[pid] ? M.periods[pid].label : '—');
M.pDate    = (pid)=> (M.periods[pid] ? M.periods[pid].date  : '—');

// item families (for ABC/XYZ + selector grouping)
const _FAMILY = {
  'TPA-4471':'Bearings', 'TPA-9904':'Valvetrain', 'TPA-3215':'Rings',
  'TPA-2188':'Rods', 'TPA-5540':'Pumps', 'TPA-7722':'Timing',
};
// item = { id, code, name, kind:'FG'|'part', uom, family } — used everywhere
M.items = M.products.filter(p=>p.cat==='Finished').map(p=>({
  id:p.sku, code:p.sku, name:p.name, kind:'FG', uom:'unit', family:_FAMILY[p.sku]||'General',
}));
M.partsOf = (sku)=> M.bom.map(b=>({ id:b.part, code:b.part, name:b.name, kind:'part', uom:'unit', qty:b.qty, lt:b.lt, sup:b.sup }));
M.itemById = (id)=> M.items.find(i=>i.id===id) || M.items[0];

// (R14) Yield-loss / expiry master fields, defaulted so the solvers' real levers are
// addressable from the UI instead of buried JS constants. salvage_rate = fraction of
// a unit's make-cost recovered when expired/excess stock is scrapped (only bites when
// shelf_life < horizon — see the Products "Yield & expiry" panel); scrap_factor =
// per-PART material lost in conversion (distinct from yield — see procurement.py
// effective_qty = qty·(1+scrap)/yield). Edit them in Products; these are just seeds.
M.products.forEach(p=>{ if(p.salvage==null) p.salvage = p.cat==='Finished' ? 0.8 : 1; });
M.bom.forEach(b=>{ if(b.scrap==null) b.scrap = 0.01; });

// bind every time-bound record to the period axis (handoff v2 §1.2 — no 'W12' literals)
M.promos.forEach((p,i)=>{ p.pid = [10,24,38][i]; });
M.costEvents.forEach((e,i)=>{ e.pid = [6,12,20,29][i]; });
M.otifLedger.forEach((o)=>{ /* due/got already period-ish; leave for ledger realism */ });

M.solverLabel = M.solvers.length + ' engines · ' + M.solverFamilies.length + ' families';

// ════════════════════════════════════════════════════════════════════════
// PART 7 — planning logic, solver triage & ingestion (handoff v2 Part 7).
// The layer that turns "16 disconnected engines" into a planning SYSTEM.
// ════════════════════════════════════════════════════════════════════════

// ── 7.3 — adaptive planning profile: captured in Setup, GATES the spine ──
M.planningProfile = {
  makePolicy:'MTS + MTO',   // pure MTO + ample capacity → hide Profit-mix
  capacity:'tight',         // 'tight' | 'ample' — ample hides Profit-mix
  imports:true,             // false → hide landed-cost, FX, incoterms
  lines:'many',             // '1' | 'many' — 1 hides Sequencing
  distribution:'network',   // 'single' | 'network' — single hides Transport
  externalForecast:false,   // true → hide Demand model-competition (7.5)
};
// derive which capabilities each profile answer switches OFF (true = gated off)
M.profileGate = (p)=>({
  profitmix:    p.capacity === 'ample',          // ample capacity → make everything, no mix
  sequencing:   p.lines === '1',                 // single line → no run-order decision
  transport:    p.distribution === 'single',     // single-site → nothing to ship
  landed:       !p.imports,                       // domestic only → no landed cost / FX / incoterms
  demandModels: p.externalForecast,              // forecast loaded → skip model competition
});
// stage-level gates (used by the nav rail to dim a whole stage)
M.stageGate = (p)=>{ const g = M.profileGate(p); return { logistics: g.transport }; };

// ── 7.1 — the planning SPINE: order + what is CONDITIONAL ──
// `gate` references a profileGate key; when that key is true the step is skipped.
M.spine = [
  { n:1, id:'demand',    go:'demand',     name:'Demand',       out:'committed demand · item · period',  when:'always' },
  { n:2, id:'aggregate', go:'plan',       name:'Aggregate',    out:'level-vs-chase · capacity duals',   when:'skip if capacity ample',  gate:'profitmix' },
  { n:3, id:'profitmix', go:'console',    name:'Profit Mix',   out:'which products win scarce hours',   when:'only if capacity binds',  gate:'profitmix' },
  { n:4, id:'mps',       go:'production', name:'MPS',          out:'time-phase qty · day in fence',     when:'always' },
  { n:5, id:'mrp',       go:'sourcing',   name:'MRP / Procure',out:'explode BOM → what · when · who',   when:'always' },
  { n:6, id:'sequence',  go:'production', name:'Sequence',     out:'run order · changeover-min',        when:'skip if 1 line',          gate:'sequencing' },
  { n:7, id:'transport', go:'logistics',  name:'Transport',    out:'move FG out',                       when:'skip if single-site',     gate:'transport' },
  { n:8, id:'risk',      go:'scenarios',  name:'Risk · MC/CVaR',out:'stress the plan',                  when:'optional overlay' },
  { n:9, id:'capital',   go:'finance',    name:'Capital',      out:'invest where a dual persists',      when:'optional' },
];

// ── 7.2 — the solver IO contract: rendered on every result card ──
// keyed by engine id (console `sel`); answers · inputs · output · feeds.
M.solverIO = {
  forecast:        { answers:'future demand',                 from:'history · events',                 feeds:'Aggregate · Profit-mix ceiling' },
  aggregate:       { answers:'can we meet it? level/chase',    from:'forecast · capacity · labour cost', feeds:'Profit-mix · Capital · MPS' },
  disaggregate:    { answers:'split envelope to SKUs',         from:'aggregate plan',                   feeds:'MPS' },
  reconcile:       { answers:'close the S&OP loop',            from:'profit-mix ⇄ aggregate',           feeds:'committed plan' },
  profitmix:       { answers:'mix when capacity binds',        from:'demand ceiling · MTO floor · margin', feeds:'MPS · Procurement' },
  procurement:     { answers:'what / when / who to buy',       from:'MPS · BOM · on-hand · contracts',  feeds:'Sourcing · Cash' },
  production:      { answers:'time-phase the build',           from:'mix · lines · lot size',           feeds:'MRP · Sequencing' },
  sequencing:      { answers:'order on the line',              from:'jobs · changeover matrix',         feeds:'shop floor' },
  lotsizing:       { answers:'order quantity / batching',      from:'demand · setup · holding',         feeds:'Procurement · MPS' },
  transport:       { answers:'ship the FG',                    from:'flows · lanes · modes',            feeds:'3PL booking' },
  allocation:      { answers:'DC → customer split',            from:'demand · DC stock',                feeds:'Transport' },
  consolidate:     { answers:'merge shipments',                from:'lanes · volumes',                  feeds:'Transport' },
  montecarlo:      { answers:'how fragile is the plan',        from:'distributions · base plan',        feeds:'hedging · Capital' },
  cvar:            { answers:'worst-case tail cost',           from:'distributions · base plan',        feeds:'risk-averse plan' },
  capital:         { answers:'add capacity?',                  from:'duals · CapEx · WACC',             feeds:'Finance verdict' },
  capital_capacity:{ answers:'how much capacity to add',       from:'persistent duals · CapEx',         feeds:'Finance verdict' },
};

// ════════════════════════════════════════════════════════════════════════
// AUTHORITATIVE SOLVER TAXONOMY (audit fix) — what each engine ACTUALLY is.
// Read straight off each module's docstring + variable categories in the .py:
//   • MILP  — has integer/binary decision vars (procurement, production,
//             capital_capacity, meio)
//   • LP    — continuous decision vars, valid duals (profitmix*, aggregate,
//             transport, capital*, linecap, cvar; *optional binary extension)
//   • closed-form / DP — analytical formulas, no math-program (lot_sizing,
//             policy, meio_network, disaggregate, reconcile)
//   • heuristic — combinatorial search, no LP (sequencing ATSP, consolidate)
//   • simulation — Monte-Carlo sampling, NOT an optimizer (montecarlo)
//   • statistical / ML — model competition (forecast, pattern_sensing)
// The platform was labelling half of these "MILP" — corrected here and in the
// roster. `tag` is a Tag colour. `solves` distinguishes optimiser vs not.
M.solverType = {
  forecast:        { type:'Statistical / ML',  tag:'a2', solves:false, method:'A competition of classical (Holt-Winters, ARIMA), intermittent (Croston/SBA/TSB) and ML/DL models, ranked by held-out MAPE. It fits and predicts — it does not optimise anything.' },
  aggregate:       { type:'LP',                tag:'a3', solves:true,  method:'Hax–Meal multi-period aggregate-planning linear program: continuous production / inventory / workforce over monthly buckets (level-vs-chase). Valid duals.' },
  disaggregate:    { type:'Closed-form',       tag:'w',  solves:false, method:'Proportional split of the family plan to SKUs by seasonal + working-day profile. Arithmetic, not a solver.' },
  reconcile:       { type:'Closed-form',       tag:'w',  solves:false, method:'Iterative S&OP reconciliation — feeds production back into the mix until the gap closes. Arithmetic loop.' },
  profitmix:       { type:'LP',                tag:'a3', solves:true,  method:'A TRUE linear program maximising contribution margin (continuous q[k], x[k,l]); emits shadow prices, reduced costs and crossover. Optional binary open_line for multi-line.' },
  procurement:     { type:'MILP',              tag:'k',  solves:true,  method:'Mixed-integer program: continuous buy/produce quantities + BINARY setup/order indicators (y, o). Integer ⇒ no valid duals.' },
  production:      { type:'MILP',              tag:'k',  solves:true,  method:'Mixed-integer scheduler: continuous build quantities + BINARY produce/changeover indicators over lines × periods.' },
  sequencing:      { type:'Heuristic (ATSP)',  tag:'v',  solves:true,  method:'Shortest Hamiltonian path over the asymmetric changeover matrix — exact (Held-Karp) for few SKUs, nearest-neighbour + local search above. Combinatorial, no LP.' },
  lotsizing:       { type:'Closed-form / DP',  tag:'v',  solves:true,  method:'EOQ (Wilson), POQ, (s,S), EPQ and Wagner-Whitin dynamic programming. Analytical / DP — not a math-program.' },
  transport:       { type:'LP',                tag:'a3', solves:true,  method:'Transportation / min-cost-flow linear program: continuous shipment quantities x[i,j] minimising lane cost. Valid duals.' },
  allocation:      { type:'LP',                tag:'a3', solves:true,  method:'DC→customer assignment as a weighted min-cost flow LP.' },
  consolidate:     { type:'Heuristic',         tag:'v',  solves:true,  method:'LTL→FTL truck consolidation by ⌈Σ truck-fractions⌉ — a packing rule, not an optimiser.' },
  montecarlo:      { type:'Simulation',        tag:'a4', solves:false, method:'Monte-Carlo: thousands of demand/cost draws replayed against the committed plan to get a fill / cost distribution. Sampling, not optimisation.' },
  cvar:            { type:'Stochastic LP',     tag:'a4', solves:true,  method:'Rockafellar–Uryasev CVaR newsvendor: a scenario-based linear program minimising the β-tail cost. Continuous, valid duals.' },
  capital:         { type:'LP',                tag:'gn', solves:true,  method:'Capital-budgeting LP: maximise portfolio NPV under a budget (0–1 selection variables, continuous by default — an LP relaxation of the knapsack).' },
  capital_capacity:{ type:'MILP',              tag:'k',  solves:true,  method:'Multi-period capacity expansion with BINARY invest[i,t] timing + budget rollover. True mixed-integer.' },
  meio:            { type:'MILP',              tag:'k',  solves:true,  method:'Graves–Willems guaranteed-service placement: INTEGER service times + BINARY hold flags over the assembly tree.' },
  meionet:         { type:'Closed-form',       tag:'w',  solves:false, method:'Square-root-law risk pooling across the SKUs that share a part — an analytical consolidation, not a math-program.' },
  policy:          { type:'Closed-form',       tag:'w',  solves:false, method:'(s,S) / (R,Q) reorder policy from EOQ + z·σ safety stock (Hadley-Whitin). Formulas, not a solver.' },
};

// ── TERM → INPUT PROVENANCE (audit fix) — does every term in the model actually
// have a DEFINE-section input feeding it, or is the solver carrying capability we
// never wire (the "too much stuff")? Per headline engine: the objective, decision
// vars, constraints, each cost/RHS term mapped to the tab that supplies it
// (wired:true) or honestly flagged as defaulted inside the .py (wired:false), and
// `extras` = modelled capability with NO input surface at all. Authored from the
// .py docstrings + the payload builders in store.jsx / the stage tabs.
M.solverModel = {
  forecast: {
    objective:'minimise held-out forecast error (MAPE) across competing models — then predict h periods ahead',
    vars:['fitted model parameters per candidate (HW/ARIMA/ML/…)','the winning forecast series'],
    constraints:['none — it is an estimator, not a feasibility problem'],
    terms:[
      { t:'demand history', src:'Demand → history / CSV import', wired:true },
      { t:'promo flags', src:'Demand → Promotions', wired:true },
      { t:'holiday calendar', src:'Setup / Demand → Holidays', wired:true },
      { t:'season length · horizon · grain', src:'derived from the grain toggle', wired:true },
    ], extras:['external-forecast bypass (gate)'] },
  profitmix: {
    objective:'maximise Σ (sell_price − variable_cost)·q[k] − Σ line fixed/open costs',
    vars:['q[k] ≥ 0 units per SKU (continuous)','x[k,l] units of k on line l','open_line[l] binary (optional)'],
    constraints:['demand ceiling (forecast) & MTO floor','shared + per-line capacity (hours)','budget','material availability (BOM)','warehouse space'],
    terms:[
      { t:'sell_price', src:'Products → price', wired:true },
      { t:'variable_cost', src:'Products → cost', wired:true },
      { t:'demand ceiling (forecast)', src:'Demand → committed series', wired:true },
      { t:'cycle_time / capacity hrs', src:'Production → stage cycle time, line hours', wired:true },
      { t:'material availability', src:'Products → BOM (qty_per, yield)', wired:true },
      { t:'mto_orders floor', src:'Products → MTO order book (firm orders) → min_quantity', wired:true },
      { t:'budget (₹ cap)', src:'— defaulted in profitmix.py (no input)', wired:false },
      { t:'warehouse space', src:'— defaulted (no input)', wired:false },
    ], extras:['dedicated/fixed-open line economics','planning_mode · shelf_life','salvage_rate'] },
  procurement: {
    objective:'minimise setup + FG holding + production + expiry + shortage + RM purchase + RM holding + RM ordering',
    vars:['p[k,t] produce qty (continuous)','r[i,t] RM order qty','y[k,t] BINARY produce flag','o[i,t] BINARY order flag'],
    constraints:['inventory balance (FG & RM)','BOM material requirement','capacity','service-level safety stock','MOQ / shelf-life'],
    terms:[
      { t:'demand', src:'Demand → committed series', wired:true },
      { t:'BOM qty_per · yield', src:'Products → BOM', wired:true },
      { t:'part cost → landed', src:'Network contracts + Sourcing → duty/freight', wired:true },
      { t:'lead_time', src:'Products / Network → supplier LT', wired:true },
      { t:'ordering · setup cost', src:'Products → costs', wired:true },
      { t:'service_level', src:'Sourcing → solver param', wired:true },
      { t:'carry / holding rate', src:'Sourcing → carry rate = Finance WACC + holding spread (carryRate)', wired:true },
      { t:'budget · early-pay · inflation', src:'— defaulted (no input)', wired:false },
    ], extras:['regime-aware sourcing','VMI','CVaR fill-rate sourcing','supplier & FX concentration caps','transport disruptions','milk-run / terminal-anchor','RM warehouse area/volume limits','working-capital & locked-PO replan'] },
  production: {
    objective:'minimise setup + overtime + makespan penalty + FG holding',
    vars:['build[k,l,t] qty (continuous)','run[k,l,t] BINARY produce flag','changeover indicators (binary)'],
    constraints:['line capacity (hours, OEE)','changeover time','inventory balance ≥ committed demand','campaign minimum run'],
    terms:[
      { t:'required_qty (demand)', src:'Demand → committed series', wired:true },
      { t:'cycle_time · OEE', src:'Production → stage editor', wired:true },
      { t:'changeover matrix', src:'Production → changeover (editable)', wired:true },
      { t:'line hours · shifts · workers', src:'Production → line/stage editor', wired:true },
      { t:'holding cost', src:'Plan / Production → solver param', wired:true },
      { t:'overtime · labor rate', src:'Production → solver param', wired:true },
      { t:'campaign_min_run', src:'Production → ProdParams', wired:true },
    ], extras:['salaried-vs-hourly labour mode','headcount / OT caps','rehire-notice cost','shared-stage ids','parallelism','planned maintenance'] },
  aggregate: {
    objective:'minimise regular + overtime production + holding + backorder + hire + fire + wage',
    vars:['P,O,I,B ≥ 0 (production/OT/inventory/backorder)','W,H,F workforce (continuous, optional integer)'],
    constraints:['inventory balance','workforce balance (W=W₋₁+H−F)','capacity = rate·W','min/max workforce ≤ line registry'],
    terms:[
      { t:'forecast', src:'Demand → committed series', wired:true },
      { t:'reg / OT / holding / backorder cost', src:'Plan → cost inputs', wired:true },
      { t:'hire / fire / wage', src:'Plan → cost inputs', wired:true },
      { t:'rate_per_worker', src:'Plan → cost inputs', wired:true },
      { t:'min/max workforce', src:'derived from line registry capacity', wired:true },
      { t:'labor_hours_per_unit', src:'— defaulted to 1 (no input)', wired:false },
      { t:'init inventory / workforce', src:'— seed constant', wired:false },
      { t:'safety stock · ending-inv target', src:'— defaulted (no input)', wired:false },
    ], extras:['integer-workforce toggle'] },
  transport: {
    objective:'minimise Σ cost_matrix[i,j]·x[i,j] (lane cost)',
    vars:['x[i,j] ≥ 0 shipment qty origin→dest (continuous)'],
    constraints:['supply at each origin','demand at each destination'],
    terms:[
      { t:'demand at destinations', src:'Demand → committed series', wired:true },
      { t:'supply / DC stock', src:'Network → on-hand', wired:true },
      { t:'cost_matrix (lane rate × distance)', src:'Network → lanes', wired:true },
      { t:'weight per unit', src:'derived (SKU weight)', wired:true },
      { t:'customs / import duty', src:'— defaulted (no input)', wired:false },
      { t:'demand spike / stockout risk', src:'— defaulted (no input)', wired:false },
    ], extras:['mode overrides','carrier tracking','disruption sensing'] },
  capital: {
    objective:'maximise Σ NPVᵢ·xᵢ subject to budget',
    vars:['xᵢ ∈ [0,1] select option i (continuous LP-relaxation; binary optional)'],
    constraints:['Σ capexᵢ·xᵢ ≤ budget','mutual exclusivity groups','dependencies'],
    terms:[
      { t:'capex per option', src:'Finance → Investment options', wired:true },
      { t:'annual cash flow', src:'Finance → Investment options', wired:true },
      { t:'WACC (discount)', src:'Finance → WACC card', wired:true },
      { t:'residual value · useful life', src:'Finance → Investment options', wired:true },
      { t:'budget cap', src:'Finance → CapEx budget/yr (config.finCapexBudget)', wired:true },
      { t:'exclusivity / dependencies', src:'— defaulted (no input)', wired:false },
    ], extras:['buy-vs-lease split'] },
  montecarlo: {
    objective:'(none — simulation) estimate the fill-rate & cost DISTRIBUTION of the committed plan',
    vars:['random demand & cost draws per run (not decisions)'],
    constraints:['replays the cached production schedule / base-stock policy'],
    terms:[
      { t:'mean demand + MAPE (σ)', src:'Demand → committed + forecast error', wired:true },
      { t:'unit cost · sell price', src:'Products → cost / price', wired:true },
      { t:'service level', src:'Sourcing → solver param', wired:true },
      { t:'policy (production plan)', src:'cached production solve', wired:true },
      { t:'prod lead-time + CV', src:'— defaulted (no input)', wired:false },
      { t:'demand–cost correlation', src:'— defaulted (no input)', wired:false },
    ], extras:['per-SKU bill draw','shelf-life expiry in the sim'] },
  cvar: {
    objective:'minimise CVaR_β (expected cost in the worst β-tail) of the newsvendor position',
    vars:['Q order-up-to ≥ 0','α VaR level (free)','o,u,z ≥ 0 scenario over/under/excess-tail'],
    constraints:['z_s ≥ L_s − α (tail linearisation) per sampled scenario'],
    terms:[
      { t:'mean & std of demand', src:'derived from committed demand + forecast error', wired:true },
      { t:'β (tail level)', src:'Scenarios → governed param', wired:true },
      { t:'holding · shortage cost', src:'— defaulted in cvar.py (no input)', wired:false },
    ], extras:['scenario count n_scenarios'] },
};

// ── 7.4 — item-method routing: not everything needs MILP ──
// AX/AY coupled → optimized (MILP). CZ stable → autopilot (s,S)/ROP/EOQ.
M.itemMethod = (sku)=>{
  const p = M.products.find(x=>x.sku===sku); if(!p) return 'optimized';
  return (p.abc !== 'A' && p.xyz !== 'X') ? 'autopilot' : 'optimized';
};
M.methodMeta = {
  autopilot:{ label:'autopilot (s,S)', tag:'g', note:'independent-demand, stable, low-value — managed by a reorder rule, no solver' },
  optimized:{ label:'optimized (LP/MILP)', tag:'v', note:'dependent / coupled decision — shared capacity, MOQs, price breaks, budget split → LP/MILP optimizer' },
};

// ── 7.5 — two ingestion modes (replace the toy entry grid) ──
M.ingestModes = [
  { id:'history',  label:'History import',  schema:'date · item · location · channel · qty [· price]', note:'tidy long format · any length (12/24/36+) · any grain → stored daily, rolled to bucket. The model competition runs on YOUR data.', drops:'→ Demand model competition' },
  { id:'forecast', label:'Forecast import', schema:'item · location · period · qty', note:'already forecast elsewhere — model competition is bypassed and labelled "external forecast loaded".', drops:'→ straight to Aggregate / Profit-mix' },
  { id:'manual',   label:'Manual grid',     schema:'item × period cells', note:'small-case / override tool only — never the primary path for real data.', drops:'→ editable cells below' },
];

// ── 7.6 — FX rate table with as-of date (every $→₹ reads this) ──
M.fxRates = { asOf:'30 May 2026 · 14:32 IST', base:'INR', rows:[
  { ccy:'USD', rate:84.20, src:'RBI ref' },
  { ccy:'EUR', rate:91.40, src:'RBI ref' },
  { ccy:'JPY', rate:0.563, src:'RBI ref' },
]};

// readiness: name the missing input + where to fix it (7.6 — block, don't decorate)
M.readiness.forEach(r=>{ if(!r.ready){
  if(r.solver==='Transport')   { r.missing='Lanes & 3PL rates'; r.fixGo='network'; r.fixLabel='Network'; }
  if(r.solver==='Monte Carlo') { r.missing='Input distributions'; r.fixGo='scenarios'; r.fixLabel='Scenarios'; }
}});

// ── per-item DAILY demand history (the finest grain) ───────────────────────
// Real orgs plan at DAY level so demand spikes are visible and production can be
// scheduled around them; weekly/monthly views are roll-ups of the daily signal.
// Deterministic demo generator (seed per SKU): weekly seasonality (weekend dip)
// + slow drift + a few promo spikes + mild noise. This is SEED INPUT data — the
// equivalent of an uploaded history CSV — NOT a fabricated result.
function _seededDaily(days, base, seed){
  let s = (Math.abs(seed||1)) % 233280;
  const rnd = ()=>{ s = (s*9301 + 49297) % 233280; return s/233280; };
  const out = [];
  for(let i=0;i<days;i++){
    const dow    = i % 7;
    const weekly = dow===6 ? 0.45 : dow===5 ? 0.75 : 1.0;          // weekend dip
    const drift  = 1 + 0.0012*i;                                    // slow growth
    const spike  = (i===44 || i===119) ? 1.7 : (i===89 ? 1.4 : 1);  // promo days
    const noise  = 0.82 + rnd()*0.36;
    out.push(Math.max(0, Math.round(base * weekly * drift * spike * noise)));
  }
  return out;
}
M.DAILY_HISTORY_DAYS = 180;
M.dailyHistoryFor = (sku)=>{
  const p = M.products.find(x=>x.sku===sku);
  const annual = p ? p.demand : 3000;
  const base = Math.max(1, Math.round(annual/365));
  const seed = parseInt(String(sku||'4471').replace(/\D/g,''),10) || 4471;
  return _seededDaily(M.DAILY_HISTORY_DAYS, base, seed);
};
// roll a finer series up to a coarser bucket (sum within each bucket).
M.bucketSeries = (series, size)=>{ const o=[]; for(let i=0;i<series.length;i+=size) o.push(series.slice(i,i+size).reduce((a,b)=>a+b,0)); return o; };
// history for an item AT a chosen grain. day = daily signal · week = 7-day
// buckets · month = the 24-month seasonal series scaled to this item (annual
// seasonality genuinely needs ≥24 monthly points, which the daily window lacks).
M.historyAt = (sku, grain)=>{
  if(grain==='monthly'){
    const p = M.products.find(x=>x.sku===sku);
    const implied = M.history24.reduce((a,b)=>a+b,0)/2;   // 24 months = 2 years
    const k = (p && implied) ? p.demand/implied : 1;
    return M.history24.map(v=>Math.max(0, Math.round(v*k)));
  }
  const daily = M.dailyHistoryFor(sku);
  return grain==='weekly' ? M.bucketSeries(daily, 7) : daily;
};
M.seasonFor  = (grain)=> grain==='daily' ? 7  : grain==='weekly' ? 13 : 12;
M.horizonFor = (grain)=> grain==='daily' ? 30 : grain==='weekly' ? 13 : 12;
M.grainLabel = (grain)=> grain==='daily' ? 'day' : grain==='weekly' ? 'week' : 'month';

// ── honesty (AUDIT A4): the solver-network status/objective were fabricated
// ("PROFIT · ₹6.84 Cr") and shown though nothing had run. Neutralise to a truthful
// idle state — the engine TYPE stays (real), the result reads "—" until a live run.
// (R13: the pipeline ribbon is now fully live off the solve cache, so its seed —
// M.pipeline — was deleted outright rather than neutralised here.)
M.solvers.forEach(s=>{ s.status='idle'; s.obj='—'; });

window.M = M;
window.MOCK = M;
window.buildPeriods = buildPeriods;
window.productionWorkDays = productionWorkDays;
