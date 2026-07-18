import { useState } from "react";
import {
  Activity,
  Bell,
  BookOpen,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleCheckBig,
  Clock3,
  FileCheck2,
  FileText,
  Gauge,
  HelpCircle,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  MoreHorizontal,
  PackageCheck,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  UserRound,
  Users,
  X,
} from "lucide-react";

const navItems = [
  { id: "home", label: "Anasayfa", icon: LayoutDashboard },
  { id: "invoices", label: "Faturalar", icon: FileText },
  { id: "clients", label: "Mükellefler", icon: Users },
  { id: "agents", label: "AI Ajanları", icon: Bot },
  { id: "settings", label: "Ayarlar", icon: Settings },
];

const invoiceRows = [
  { name: "Elektrik faturası — Haziran", supplier: "Örnek Enerji A.Ş.", amount: "8.742,16 TL", state: "Kontrol bekliyor", tone: "amber" },
  { name: "Kargo hizmeti", supplier: "Örnek Kargo A.Ş.", amount: "1.286,40 TL", state: "Onaylanabilir", tone: "green" },
  { name: "Ofis sarf malzemeleri", supplier: "Örnek Ticaret Ltd.", amount: "3.460,00 TL", state: "Küçük düzeltme", tone: "blue" },
];

function Logo() {
  return (
    <div className="brand">
      <div className="brand-mark">F</div>
      <div><strong>Fisero</strong><span>Özel Muhasebe<br />Operasyon Portalı</span></div>
    </div>
  );
}

function Sidebar({ page, setPage, open, close }) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-head"><Logo /><button className="icon-btn mobile-only" onClick={close}><X size={20} /></button></div>
      <nav>
        {navItems.map(({ id, label, icon: Icon }) => (
          <button key={id} className={page === id ? "active" : ""} onClick={() => { setPage(id); close(); }}>
            <Icon size={20} strokeWidth={1.8} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-user">
        <div className="avatar">ÖY</div>
        <div><strong>Ömer Yağcı</strong><span>Mali Müşavir</span></div>
      </div>
    </aside>
  );
}

function Topbar({ page, invoiceMode, setInvoiceMode, openMenu }) {
  const title = navItems.find((item) => item.id === page)?.label ?? "Anasayfa";
  return (
    <header className="topbar">
      <div className="topbar-title">
        <button className="icon-btn menu-btn" onClick={openMenu}><Menu size={22} /></button>
        <h1>{page === "invoices" && invoiceMode === "review" ? "Fatura İşleme" : page === "invoices" ? "Aktarıma Hazır" : title}</h1>
      </div>
      {page === "invoices" ? (
        <div className="invoice-mode-switch" aria-label="Fatura görünümü">
          <button className={invoiceMode === "review" ? "active" : ""} onClick={() => setInvoiceMode("review")}>İşleme</button>
          <button className={invoiceMode === "export" ? "active" : ""} onClick={() => setInvoiceMode("export")}><PackageCheck size={16} /> Aktarıma Hazır <b>12</b></button>
        </div>
      ) : <div />}
      <div className="topbar-actions">
        <button><Bell size={18} /> Bildirimler <b>3</b></button>
        <button className="desktop-only"><HelpCircle size={18} /> Yardım</button>
        <div className="user-status"><span>Oturum açık</span><strong>Ömer Yağcı</strong></div>
      </div>
    </header>
  );
}

function Metric({ icon: Icon, label, value, note }) {
  return <article className="metric"><div className="metric-icon"><Icon size={21} /></div><div><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div></article>;
}

function Home({ go }) {
  return (
    <div className="page-stack">
      <section className="notice"><Sparkles size={18} /><div><strong>Ajanlar çalışıyor</strong><span>Belge kuyruğunda olağan dışı bir durum yok.</span></div><button onClick={() => go("agents")}>Ajanları gör</button></section>
      <div className="metrics-grid">
        <Metric icon={Upload} label="Bugün yüklenen" value="38" note="5 mükellef" />
        <Metric icon={FileCheck2} label="Kontrol bekleyen" value="17" note="6 tanesi onaylanabilir" />
        <Metric icon={PackageCheck} label="Aktarıma hazır" value="12" note="Toplam 184.260 TL" />
        <Metric icon={MessageSquareText} label="Ek bilgi bekleyen" value="2" note="İnsan tarafından işaretlendi" />
      </div>
      <div className="home-grid">
        <section className="panel">
          <div className="panel-title"><div><span>ÖNCELİKLİ İŞLER</span><h2>Bugün tamamlanması gerekenler</h2></div><strong>5 iş</strong></div>
          <div className="task-list">
            {[
              ["3 fatura tek tıkla onaylanabilir", "Örnek İşitme Merkezi", "invoices"],
              ["2 kural adayı onay bekliyor", "Kargo gideri · Elektrik gideri", "agents"],
              ["Aktarım paketi hazırlanabilir", "Haziran 2026 · 12 fiş", "invoices"],
            ].map(([title, sub, target], i) => <button key={title} onClick={() => go(target)}><div className={`task-dot t${i}`} /><div><strong>{title}</strong><span>{sub}</span></div><ChevronRight size={19} /></button>)}
          </div>
        </section>
        <section className="panel compact-agents">
          <div className="panel-title"><div><span>AI AJANLARI</span><h2>Kısa sağlık özeti</h2></div><button className="text-btn" onClick={() => go("agents")}>Ayrıntılar</button></div>
          <div className="agent-health-grid">
            {["Belge ajanı", "Hesap ajanı", "Cari ajanı", "Araştırma ajanı"].map((name, i) => <div key={name}><Bot size={19} /><span>{name}</span><strong>{i === 3 ? "Hazır" : "Çalışıyor"}</strong></div>)}
          </div>
        </section>
      </div>
    </div>
  );
}

function InvoiceReview() {
  return (
    <div className="page-stack invoice-review">
      <div className="preserve-note"><ShieldCheck size={17} /><span><strong>Prototip notu:</strong> Aşağıdaki Fatura İşleme yüzeyi korunuyor. Yeni geçiş yalnızca yukarıdaki başlık alanında.</span></div>
      <section className="review-toolbar panel">
        <label><span>Mükellef</span><select><option>Örnek İşitme Merkezi Ltd.</option></select></label>
        <label className="search-field"><span>Ara</span><div><Search size={17} /><input placeholder="Belge adı, tür, tutar..." /></div></label>
        <div className="invoice-tabs"><button className="active">Alış <b>24</b></button><button>Satış <b>11</b></button></div>
        <div className="queue-filters"><span>İş kuyruğu</span><button className="active">Onaylanabilir <b>6</b></button><button>Küçük düzeltme <b>8</b></button><button>Manuel / riskli <b>3</b></button><button>Tümü <b>24</b></button></div>
      </section>
      <section className="agent-strip">
        {[['Belge ajanı','Tamamlandı'],['Hesap ajanı','760 Kargo Gideri'],['Cari ajanı','Eşleşti'],['Araştırma ajanı','Gerekmedi']].map(([a,b]) => <div key={a}><span>{a}</span><strong>{b}</strong></div>)}
        <div className="stepper"><span>2 / 6</span><button><ChevronLeft size={17} /></button><button><ChevronRight size={17} /></button></div>
      </section>
      <section className="review-main">
        <div className="panel document-preview"><div className="panel-title"><h2>Orijinal belge</h2><button className="text-btn">Yeni pencerede aç</button></div><div className="paper"><div className="paper-logo">ÖRNEK KARGO</div><div className="paper-lines"><i /><i /><i /><i /></div><div className="paper-total">Toplam: 1.286,40 TL</div></div></div>
        <div className="panel journal"><div className="panel-title"><div><span>MUHASEBE FİŞİ</span><h2>Hazırlanan kayıt</h2></div><span className="status green">Onaylanabilir</span></div>
          <div className="journal-row head"><span>Hesap</span><span>Açıklama</span><span>Borç</span><span>Alacak</span></div>
          <div className="journal-row"><strong>760.03.010</strong><span>Kargo gideri</span><span>1.072,00</span><span>—</span></div>
          <div className="journal-row"><strong>191.01</strong><span>İndirilecek KDV</span><span>214,40</span><span>—</span></div>
          <div className="journal-row"><strong>320.01.004</strong><span>Örnek Kargo A.Ş.</span><span>—</span><span>1.286,40</span></div>
          <div className="explain"><Bot size={18} /><p><strong>Neden böyle hazırladım?</strong> Bu cari daha önce kargo hizmeti olarak onaylandı. Aynı anlam ve vergi davranışı eşleşti.</p></div>
          <div className="journal-actions"><button className="secondary"><MoreHorizontal size={18} /> Diğer işlemler</button><button className="primary"><Check size={18} /> Onayla ve sonrakine geç</button></div>
        </div>
      </section>
    </div>
  );
}

function ExportReady() {
  const [selected, setSelected] = useState([0,1,2]);
  function toggle(i){ setSelected((s) => s.includes(i) ? s.filter((x)=>x!==i) : [...s,i]); }
  return (
    <div className="page-stack">
      <section className="export-hero panel"><div><span>FATURALAR / AKTARIMA HAZIR</span><h2>Onaylanan fişleri son kez kontrol et</h2><p>Bu alan Fatura İşleme ekranından ayrıdır. Günlük inceleme yüzeyini kalabalıklaştırmaz.</p></div><div className="hero-count"><strong>12</strong><span>hazır fiş</span></div></section>
      <section className="export-summary">
        <Metric icon={CircleCheckBig} label="Seçili" value={`${selected.length} fiş`} note="Toplu pakete eklenecek" />
        <Metric icon={Gauge} label="Kontrol" value="12 / 12" note="Denge ve vergi kontrolü geçti" />
        <Metric icon={Clock3} label="Dönem" value="Haziran 2026" note="Alış faturaları" />
      </section>
      <section className="panel export-table-panel">
        <div className="panel-title"><div><span>HAZIR FİŞLER</span><h2>Aktarım seçimi</h2></div><div className="toolbar-actions"><button className="secondary">Tümünü seç</button><button className="primary"><PackageCheck size={17}/> Paket hazırla</button></div></div>
        <div className="export-list">
          {invoiceRows.map((row,i)=><button key={row.name} className={selected.includes(i)?"selected":""} onClick={()=>toggle(i)}><span className="check-box">{selected.includes(i)&&<Check size={14}/>}</span><div><strong>{row.name}</strong><span>{row.supplier}</span></div><b>{row.amount}</b><span className={`status ${row.tone}`}>{row.state}</span><ChevronRight size={18}/></button>)}
        </div>
      </section>
    </div>
  );
}

function Agents() {
  const [tab,setTab]=useState("agents");
  return <div className="page-stack"><div className="section-tabs"><button className={tab==='agents'?'active':''} onClick={()=>setTab('agents')}>Ajanlar</button><button className={tab==='learning'?'active':''} onClick={()=>setTab('learning')}>Öğrenme ve Kurallar <b>2</b></button><button className={tab==='research'?'active':''} onClick={()=>setTab('research')}>Araştırma / Bilgi Havuzu</button></div>
    {tab==='agents'&&<div className="agent-cards">{[['Belge ajanı','38','%96'],['Hesap ajanı','34','%91'],['Cari ajanı','37','%98'],['Araştırma ajanı','9','%89']].map(([name,jobs,rate])=><article className="panel" key={name}><div className="agent-card-head"><div><Bot size={21}/><h2>{name}</h2></div><span className="status green">Çalışıyor</span></div><div className="agent-stats"><div><span>Bugün dokunduğu iş</span><strong>{jobs}</strong></div><div><span>Değişmeden onay</span><strong>{rate}</strong></div><div><span>Düzeltme</span><strong>{name==='Hesap ajanı'?'3':'1'}</strong></div><div><span>Kapasite</span><strong>Normal</strong></div></div><button className="agent-detail">Ayrıntıları aç <ChevronDown size={17}/></button></article>)}</div>}
    {tab==='learning'&&<section className="panel rules"><div className="panel-title"><div><span>AJAN EĞİTİMİ</span><h2>Öğrenme ve Kurallar</h2></div><button className="secondary">Tüm kuralları gör</button></div>{[['Yurtiçi Kargo → Kargo gideri','Müşavir özel · Cari anlamı paylaşımlı','1 kez değişikliksiz onaylandı'],['Elektrik dağıtım hizmeti → Elektrik gideri','Mükellef özel · Vergi davranışı eşleşmeli','Onay bekliyor']].map((r,i)=><div className="rule" key={r[0]}><div className="rule-icon"><BookOpen size={19}/></div><div><strong>{r[0]}</strong><span>{r[1]}</span><small>{r[2]}</small></div><span className={`status ${i?'amber':'green'}`}>{i?'Aday':'Aktif'}</span><button className="icon-btn"><ChevronRight size={18}/></button></div>)}</section>}
    {tab==='research'&&<div className="research-grid"><section className="panel"><div className="panel-title"><div><span>ARAŞTIRMA PROFİLİ</span><h2>Ofis bilgi profili</h2></div><span className="status green">Güncel</span></div><div className="profile-card"><strong>Özel muhasebe ofisi</strong><span>Elektrik, kargo, işitme cihazları ve perakende senaryoları</span><button className="secondary">Profili düzenle</button></div></section><section className="panel"><div className="panel-title"><div><span>KAYNAKLAR</span><h2>Bilgi kapsamı</h2></div></div>{['Ofis tarafından onaylanan bilgiler','İnternet araştırma sonuçları','Müşavir düzeltmelerinden öğrenilen anlamlar'].map((x)=><div className="source-row" key={x}><ShieldCheck size={18}/><span>{x}</span><strong>Etkin</strong></div>)}</section></div>}
  </div>
}

function Clients() {
  return <div className="page-stack"><section className="panel client-head"><div><span>MÜKELLEFLER</span><h2>Ofis portföyü</h2><p>Mükellef işlemleri bağımsız kalır; Fatura İşleme ekranına taşınmaz.</p></div><button className="primary"><Users size={17}/> Yeni mükellef</button></section><div className="client-grid">{['Örnek İşitme Merkezi Ltd.','Demo Perakende A.Ş.','Örnek Danışmanlık Ltd.'].map((name,i)=><article className="panel" key={name}><div className="client-avatar">{name[0]}</div><div><h3>{name}</h3><span>{i===0?'Sağlık ürünleri':'Hizmet ve ticaret'}</span></div><div className="client-numbers"><span>Kontrol bekleyen <b>{i+2}</b></span><span>Aktarıma hazır <b>{i+1}</b></span></div><button className="secondary">Mükellefi aç</button></article>)}</div></div>
}

function SettingsPage() {
  const [tab,setTab]=useState('office');
  return <div className="settings-layout"><aside className="settings-nav"><span>AYARLAR</span>{[['office','Ofis ve kullanıcılar',Users],['integrations','Entegrasyonlar',Activity],['ai','AI ve yancı',Sparkles],['system','Sistem ve operasyon',Gauge]].map(([id,label,Icon])=><button key={id} className={tab===id?'active':''} onClick={()=>setTab(id)}><Icon size={18}/>{label}{id==='system'&&<small>Yetkili</small>}</button>)}</aside><section className="panel settings-content">
    {tab==='office'&&<><div className="panel-title"><div><span>OFİS</span><h2>Ofis ve kullanıcılar</h2></div><button className="primary">Kullanıcı ekle</button></div><div className="setting-row"><div><strong>Ömer Yağcı</strong><span>Mali Müşavir · Ofis yöneticisi</span></div><span className="status green">Aktif</span></div><div className="setting-row"><div><strong>Muhasebe kurallarını yönetebilir</strong><span>Kuralları onaylama, değiştirme ve pasife alma yetkisi</span></div><button className="toggle on"><i/></button></div></>}
    {tab==='integrations'&&<><div className="panel-title"><div><span>BAĞLANTILAR</span><h2>Entegrasyonlar</h2></div></div>{['QNB e-Fatura / e-Arşiv','AI sağlayıcıları','Teknik servis e-postası'].map((x,i)=><div className="setting-row" key={x}><div><strong>{x}</strong><span>{i===0?'Test bağlantısı':'Yapılandırılmış'}</span></div><button className="secondary">Yönet</button></div>)}</>}
    {tab==='ai'&&<><div className="panel-title"><div><span>YAPAY ZEKA</span><h2>AI ve yancı tercihleri</h2></div></div><div className="setting-row"><div><strong>Yancının kendiliğinden tepki sıklığı</strong><span>Varsayılan olarak düşük, kritik durumlarda görünür</span></div><select><option>Düşük</option></select></div><div className="setting-row"><div><strong>Konu dışı sohbet sınırı</strong><span>Ofis kredisinin gereksiz kullanımını engeller</span></div><select><option>Dengeli</option></select></div></>}
    {tab==='system'&&<><div className="panel-title"><div><span>YETKİLİ ALANI</span><h2>Sistem ve operasyon</h2></div><span className="status green">Sistem sağlıklı</span></div><div className="ops-grid"><Metric icon={Gauge} label="AI kapasitesi" value="Normal" note="4 ajan erişilebilir"/><Metric icon={Activity} label="İşlem kuyruğu" value="3 belge" note="Olağan akış"/></div><div className="setting-row"><div><strong>Belge saklama politikası</strong><span>Ham belgeler 60 gün sonra arşivlenir</span></div><button className="secondary">Yönet</button></div><div className="setting-row"><div><strong>Operasyon geçmişi</strong><span>Yetkili kullanıcılar için teknik görünüm</span></div><button className="secondary">Aç</button></div></>}
  </section></div>
}

export function App() {
  const [page,setPage]=useState('invoices');
  const [invoiceMode,setInvoiceMode]=useState('review');
  const [menuOpen,setMenuOpen]=useState(false);
  return (
    <div className="prototype-shell">
      <div className="prototype-ribbon">TIKLANABİLİR TASLAK · GERÇEK VERİ DEĞİL</div>
      <Sidebar page={page} setPage={setPage} open={menuOpen} close={()=>setMenuOpen(false)} />
      {menuOpen&&<button className="scrim" aria-label="Menüyü kapat" onClick={()=>setMenuOpen(false)}/>} 
      <div className="main-shell">
        <Topbar page={page} invoiceMode={invoiceMode} setInvoiceMode={setInvoiceMode} openMenu={()=>setMenuOpen(true)} />
        <main className="content">
          {page==='home'&&<Home go={setPage}/>} 
          {page==='invoices'&&(invoiceMode==='review'?<InvoiceReview/>:<ExportReady/>)}
          {page==='clients'&&<Clients/>}
          {page==='agents'&&<Agents/>}
          {page==='settings'&&<SettingsPage/>}
        </main>
        <button className="sidekick" title="Yancı"><Sparkles size={20}/><span>Bir şey sor</span></button>
      </div>
    </div>
  );
}
