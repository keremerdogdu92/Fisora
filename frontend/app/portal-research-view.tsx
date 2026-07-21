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
  turkishResearchSummary,
} from "./workspace-api";

type ResearchPayload = {
  kind: string;
  key: string;
  profile_id?: string;
  expected_revision?: number;
  client_id?: string;
  query?: string;
  supplier_hint?: string;
  activity_context?: string;
  summary_tr?: string;
  category_tags?: string[];
  account_treatment?: string;
  confidence?: number;
  force?: boolean;
};

type ResearchDisplayProfile = ResearchProfileView & {
  non_authoritative_display?: {
    product_category?: string;
    account_treatment?: string;
  };
};

function nonAuthoritativeDisplay(profile?: ResearchProfileView) {
  return (profile as ResearchDisplayProfile | undefined)?.non_authoritative_display || {};
}

function sourceSummary(profile: ResearchProfileView) {
  const sources = Array.isArray(profile.sources) ? profile.sources : Array.isArray(profile.evidence) ? profile.evidence : [];
  if (!sources.length) return "Kaynak yok";
  const accepted = sources.filter((source) => source.accepted !== false).length;
  return `${accepted}/${sources.length} kaynak kabul`;
}

function categorySummary(profile?: ResearchProfileView) {
  if (!profile) return "";
  const display = nonAuthoritativeDisplay(profile);
  if (display.product_category) return display.product_category;
  if (Array.isArray(profile.common_product_categories) && profile.common_product_categories.length) {
    return profile.common_product_categories.join(", ");
  }
  return display.account_treatment || "";
}

function formatConfidence(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

function formatRunAccuracy(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value > 1 ? value : value * 100)}%`;
}

function profileResearchConfidence(profile?: ResearchProfileView) {
  return profile?.research_confidence ?? profile?.confidence;
}

function profileImpactConfidence(profile?: ResearchProfileView) {
  return profile?.accounting_impact_confidence;
}

function reviewReason(profile?: ResearchProfileView) {
  if (!profile) return "";
  if (profile.override) return "Ofis override";
  const researchConfidence = profileResearchConfidence(profile) ?? 0;
  const impactConfidence = profileImpactConfidence(profile) ?? 0;
  if (sourceSummary(profile) === "Kaynak yok") return "Kaynak yok";
  if (researchConfidence < 70) return "Kaynak guveni dusuk";
  if (impactConfidence < 70) return "Muhasebe etkisi belirsiz";
  const treatment = nonAuthoritativeDisplay(profile).account_treatment;
  if (treatment === "fixed_asset_review") return "Demirbas kontrolu";
  if (treatment === "non_deductible_review") return "KKEG kontrolu";
  if (treatment === "manual_review") return "Manuel etki";
  return "Kaynakli kanit hazir";
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
  const selectedProfile = profiles.find((profile) => profile.profile_id === selectedKey) ?? profiles[0];

  async function loadResearchData() {
    const [profilePayload, runPayload] = await Promise.all([
      fetchResearchProfiles({ apiBaseUrl, kind: "brand", ...auth }),
      fetchResearchBenchmarkRuns({ apiBaseUrl, ...auth }),
    ]);
    const nextProfiles = Array.isArray(profilePayload?.profiles) ? profilePayload.profiles : [];
    setProfiles(nextProfiles);
    setBenchmarkRuns(Array.isArray(runPayload?.runs) ? runPayload.runs : []);
    setSelectedKey((current) => current || nextProfiles[0]?.profile_id || "");
  }

  useEffect(() => {
    let cancelled = false;
    setStatus("Bilgi havuzu okunuyor.");
    void loadResearchData()
      .then(() => {
        if (!cancelled) setStatus("");
      })
      .catch(() => {
        if (!cancelled) setStatus("Bilgi havuzu sunucudan okunamadı. Yenile düğmesiyle tekrar deneyin.");
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, session?.sessionToken, session?.userId, loginUserId]);

  async function submitRefresh(payload: ResearchPayload) {
    setStatus("İşlem çalışıyor.");
    try {
      await refreshResearchProfile({ apiBaseUrl, payload, ...auth });
      await loadResearchData();
      setStatus("Bilgi havuzu güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Sunucu yanıtını operasyon ekranından kontrol edin.");
    }
  }

  async function submitOverride() {
    if (!selectedProfile) return;
    setStatus("İşlem çalışıyor.");
    try {
      await overrideResearchProfile({
        apiBaseUrl,
        payload: {
          kind: selectedProfile.kind || "brand",
          key: selectedProfile.key,
          profile_id: selectedProfile.profile_id,
          expected_revision: selectedProfile.revision,
          summary_tr: overrideSummary || selectedProfile.summary_tr || selectedProfile.summary || "",
          category_tags: (overrideCategory || categorySummary(selectedProfile))
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          account_treatment: nonAuthoritativeDisplay(selectedProfile).account_treatment || "",
          confidence: 100,
        },
        ...auth,
      });
      await loadResearchData();
      setStatus("Bilgi havuzu güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Sunucu yanıtını operasyon ekranından kontrol edin.");
    }
  }

  async function submitBenchmark() {
    setStatus("İşlem çalışıyor.");
    try {
      await runResearchBenchmark({ apiBaseUrl, ...auth });
      await loadResearchData();
      setStatus("Bilgi havuzu güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Sunucu yanıtını operasyon ekranından kontrol edin.");
    }
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
        <p className={status.includes("okunamadı") || status.includes("tamamlanamadı") ? "decision-status error" : "decision-status"}>{status || "Yeni belgelerde güvenli research sinyali kullanılır; export kapısı yine müşavir kontrolündedir."}</p>
      </div>

      <div className="panel">
        <h2>Araştırma profilleri</h2>
        <div className="basket-list">
          {profiles.length ? profiles.map((profile) => (
            <button
              className={`basket-row ${selectedProfile?.profile_id === profile.profile_id ? "active-action" : ""}`}
              key={`${profile.kind}-${profile.profile_id}`}
              onClick={() => setSelectedKey(profile.profile_id || "")}
              type="button"
            >
              <div>
                <strong>{profile.display_key || profile.key}</strong>
                <span>{turkishResearchSummary(profile)}</span>
              </div>
              <span className="status export_ready">{formatConfidence(profileResearchConfidence(profile))}</span>
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
        <Info label="Research guveni" value={formatConfidence(profileResearchConfidence(selectedProfile))} />
        <Info label="Muhasebe etkisi" value={formatConfidence(profileImpactConfidence(selectedProfile))} />
        <Info label="Kontrol nedeni" value={reviewReason(selectedProfile)} />
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
              profile_id: selectedProfile.profile_id,
              client_id: selectedProfile.client_id,
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
        <h2>Musavir kanit notu</h2>
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
        <Info label="Marka" value={formatRunAccuracy(latestRun?.metrics?.brand_accuracy)} />
        <Info label="Kategori" value={formatRunAccuracy(latestRun?.metrics?.category_accuracy)} />
        <Info label="Muhasebe etkisi" value={formatRunAccuracy(latestRun?.metrics?.accounting_impact_accuracy)} />
        <Info label="Kontrol kapisi" value={formatRunAccuracy(latestRun?.metrics?.review_gate_accuracy)} />
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
