"use client";

import { useEffect, useMemo, useState } from "react";
import { resolveApiBaseUrl } from "./features/session";
import { Info, Metric } from "./portal-shared";
import type { LocalSession, ResearchBenchmarkRunView, ResearchProfileView } from "./portal-types";
import {
  fetchResearchBenchmarkRuns,
  fetchResearchProfiles,
  overrideResearchProfile,
  refreshResearchProfile,
  runResearchBenchmark,
} from "./workspace-api";

type ResearchPayload = {
  kind: string;
  key: string;
  query?: string;
  supplier_hint?: string;
  activity_context?: string;
  summary_tr?: string;
  category_tags?: string[];
  confidence?: number;
  force?: boolean;
};

function sourceSummary(profile: ResearchProfileView) {
  const sources = Array.isArray(profile.sources) ? profile.sources : Array.isArray(profile.evidence) ? profile.evidence : [];
  if (!sources.length) return "Kaynak yok";
  const accepted = sources.filter((source) => source.accepted !== false).length;
  return `${accepted}/${sources.length} kaynak kabul`;
}

function categorySummary(profile?: ResearchProfileView) {
  if (!profile) return "";
  if (profile.product_category) return profile.product_category;
  if (Array.isArray(profile.common_product_categories) && profile.common_product_categories.length) {
    return profile.common_product_categories.join(", ");
  }
  return profile.account_treatment || "";
}

function formatConfidence(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

function formatRunAccuracy(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value > 1 ? value : value * 100)}%`;
}

function benchmarkRunTime(run: ResearchBenchmarkRunView) {
  const value = run.created_at || "";
  if (!value) return "Benchmark koşumu";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Benchmark koşumu";
  return parsed.toLocaleString("tr-TR");
}

function sortBenchmarkRuns(runs: ResearchBenchmarkRunView[]) {
  return [...runs].sort((left, right) => {
    const leftTime = new Date(left.created_at || "").getTime();
    const rightTime = new Date(right.created_at || "").getTime();
    return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime);
  });
}

export function ResearchKnowledgeView({
  loginUserId,
  session,
}: {
  loginUserId: string;
  session: LocalSession | null;
}) {
  const [profiles, setProfiles] = useState<ResearchProfileView[]>([]);
  const [benchmarkRuns, setBenchmarkRuns] = useState<ResearchBenchmarkRunView[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [refreshQuery, setRefreshQuery] = useState("");
  const [overrideSummary, setOverrideSummary] = useState("");
  const [overrideCategory, setOverrideCategory] = useState("");
  const [status, setStatus] = useState("");
  const apiBaseUrl = useMemo(
    () => resolveApiBaseUrl(typeof window === "undefined" ? "" : window.location.href),
    [],
  );
  const auth = {
    sessionToken: session?.sessionToken || "",
    userId: session?.userId || loginUserId || "mali-musavir",
  };
  const selectedProfile = profiles.find((profile) => profile.key === selectedKey) ?? profiles[0];

  async function loadResearchData() {
    const [profilePayload, runPayload] = await Promise.all([
      fetchResearchProfiles({ apiBaseUrl, kind: "brand", ...auth }),
      fetchResearchBenchmarkRuns({ apiBaseUrl, ...auth }),
    ]);
    const nextProfiles = Array.isArray(profilePayload?.profiles) ? profilePayload.profiles : [];
    setProfiles(nextProfiles);
    setBenchmarkRuns(Array.isArray(runPayload?.runs) ? runPayload.runs : []);
    setSelectedKey((current) => current || nextProfiles[0]?.key || "");
  }

  useEffect(() => {
    let cancelled = false;
    setStatus("Bilgi havuzu okunuyor.");
    void loadResearchData()
      .then(() => {
        if (!cancelled) setStatus("");
      })
      .catch((error) => {
        if (!cancelled) setStatus(error instanceof Error ? error.message : "Bilgi havuzu okunamadı.");
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, session?.sessionToken, session?.userId, loginUserId]);

  async function submitRefresh(payload: ResearchPayload) {
    setStatus("Araştırma yenileniyor.");
    await refreshResearchProfile({ apiBaseUrl, payload, ...auth });
    await loadResearchData();
    setStatus("Araştırma profili yenilendi.");
  }

  async function submitOverride() {
    if (!selectedProfile) return;
    setStatus("Ofis geneli override kaydediliyor.");
    await overrideResearchProfile({
      apiBaseUrl,
      payload: {
        kind: selectedProfile.kind || "brand",
        key: selectedProfile.key,
        summary_tr: overrideSummary || selectedProfile.summary_tr || selectedProfile.summary || "",
        category_tags: (overrideCategory || categorySummary(selectedProfile))
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        confidence: 100,
      },
      ...auth,
    });
    await loadResearchData();
    setStatus("Override kaydedildi.");
  }

  async function submitBenchmark() {
    setStatus("Benchmark çalışıyor.");
    await runResearchBenchmark({ apiBaseUrl, ...auth });
    await loadResearchData();
    setStatus("Benchmark tamamlandı.");
  }

  const sortedBenchmarkRuns = useMemo(() => sortBenchmarkRuns(benchmarkRuns), [benchmarkRuns]);
  const latestRun = sortedBenchmarkRuns[0];

  return (
    <section className="operations-grid">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Bilgi havuzu</h2>
            <span>Research cache, kaynak politikası ve manuel ofis kararları.</span>
          </div>
          <button onClick={() => void loadResearchData()} type="button">Yenile</button>
        </div>
        <div className="summary-grid compact">
          <Metric label="Profil" value={profiles.length} />
          <Metric label="Benchmark" value={benchmarkRuns.length} />
        </div>
        <p className="decision-status">{status || "Yeni belgelerde güvenli research sinyali kullanılır; export kapısı yine müşavir kontrolündedir."}</p>
      </div>

      <div className="panel">
        <h2>Araştırma profilleri</h2>
        <div className="basket-list">
          {profiles.length ? profiles.map((profile) => (
            <button
              className={`basket-row ${selectedProfile?.key === profile.key ? "active-action" : ""}`}
              key={`${profile.kind}-${profile.key}`}
              onClick={() => setSelectedKey(profile.key)}
              type="button"
            >
              <div>
                <strong>{profile.key}</strong>
                <span>{profile.summary || profile.summary_tr || categorySummary(profile) || "Özet yok"}</span>
              </div>
              <span className="status export_ready">{formatConfidence(profile.confidence)}</span>
            </button>
          )) : (
            <p className="decision-status">Henüz research profili yok.</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>Seçili profil</h2>
        <Info label="Anahtar" value={selectedProfile?.key || ""} />
        <Info label="Kategori" value={categorySummary(selectedProfile)} />
        <Info label="Güven" value={formatConfidence(selectedProfile?.confidence)} />
        <Info label="Kaynak" value={selectedProfile ? sourceSummary(selectedProfile) : ""} />
        <Info label="Durum" value={selectedProfile?.override ? "Ofis override" : selectedProfile?.status || "Cache"} />
        <input
          aria-label="Araştırma sorgusu"
          onChange={(event) => setRefreshQuery(event.target.value)}
          placeholder="Marka/model + tedarikçi"
          value={refreshQuery}
        />
        <button
          onClick={() =>
            selectedProfile &&
            void submitRefresh({
              kind: selectedProfile.kind || "brand",
              key: selectedProfile.key,
              query: refreshQuery || selectedProfile.key,
              force: true,
            })
          }
          type="button"
        >
          Manuel yenile
        </button>
      </div>

      <div className="panel">
        <h2>Ofis geneli override</h2>
        <input
          aria-label="Override kategori"
          onChange={(event) => setOverrideCategory(event.target.value)}
          placeholder="Kategori"
          value={overrideCategory}
        />
        <textarea
          aria-label="Override özeti"
          onChange={(event) => setOverrideSummary(event.target.value)}
          placeholder="Müşavir kararı"
          rows={4}
          value={overrideSummary}
        />
        <button className="primary" disabled={!selectedProfile} onClick={() => void submitOverride()} type="button">
          Override kaydet
        </button>
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Benchmark</h2>
            <span>Altın set ile bilgi havuzu eşleşmeleri.</span>
          </div>
          <button onClick={() => void submitBenchmark()} type="button">Benchmark çalıştır</button>
        </div>
        <Info label="Son başarı" value={formatRunAccuracy(latestRun?.accuracy)} />
        <Info label="Case" value={latestRun?.case_count ? String(latestRun.case_count) : ""} />
        <p className="decision-status">
          Benchmark canlı model çağırmaz; mevcut research cache ve override kayıtlarını ölçer.
        </p>
        <div className="basket-list">
          {sortedBenchmarkRuns.length ? sortedBenchmarkRuns.slice(0, 5).map((run) => (
            <div className="basket-row" key={run.run_id || run.created_at}>
              <div>
                <strong>{benchmarkRunTime(run)}</strong>
                <span>{run.passed_count ?? run.matched_count ?? 0}/{run.case_count || 0} cache eşleşmesi</span>
              </div>
              <span className="status export_added">{formatRunAccuracy(run.accuracy)}</span>
            </div>
          )) : (
            <div className="basket-row">
              <div>
                <strong>Henüz ölçüm yok</strong>
                <span>Profil yenileme veya override sonrası benchmark çalıştırılır.</span>
              </div>
              <span className="status queued">Bekliyor</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
