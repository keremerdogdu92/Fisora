const checks = [
  { label: "Hesap plani import", status: "Hazir" },
  { label: "Detay hesap tespiti", status: "Hazir" },
  { label: "120/320 cari adaylari", status: "Hazir" },
  { label: "191/391 KDV kontrolu", status: "Hazir" },
  { label: "Dengeli fis taslaklari", status: "Hazir" },
  { label: "Zirve export matrisi", status: "TBD" },
];

export default function Home() {
  return (
    <main className="shell">
      <section className="intro">
        <p className="label">Faz 0</p>
        <h1>Muhasebe operasyon otomasyonu doğrulama paneli</h1>
        <p>
          Zirve aktarım rotası, hesap planı importu ve dengeli fiş üretimi tam
          MVP başlamadan önce bu akışta doğrulanır.
        </p>
      </section>
      <section className="panel" aria-label="Faz 0 kontrol listesi">
        <h2>Kontrol Listesi</h2>
        <ul>
          {checks.map((check) => (
            <li key={check.label}>
              <span>{check.label}</span>
              <strong>{check.status}</strong>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
