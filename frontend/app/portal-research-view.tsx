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
    setStatus("Araştırma kayıtları yükleniyor.");
    void loadResearchData()
      .then(() => {
        if (!cancelled) setStatus("");
      })
      .catch(() => {
        if (!cancelled) setStatus("Araştırma kayıtları şu an alınamadı. Yenile ile tekrar deneyin.");
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, session?.sessionToken, session?.userId, loginUserId]);

  async function submitRefresh(payload: ResearchPayload) {
    setStatus("İşlem sürüyor.");
    try {
      await refreshResearchProfile({ apiBaseUrl, payload, ...auth });
      await loadResearchData();
      setStatus("Araştırma kayıtları güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Daha sonra tekrar deneyin.");
    }
  }

  async function submitOverride() {
    if (!selectedProfile) return;
    setStatus("İşlem sürüyor.");
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
      setStatus("Araştırma kayıtları güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Daha sonra tekrar deneyin.");
    }
  }

  async function submitBenchmark() {
    setStatus("İşlem sürüyor.");
    try {
      await runResearchBenchmark({ apiBaseUrl, ...auth });
      await loadResearchData();
      setStatus("Kalite ölçümü güncellendi.");
    } catch {
      setStatus("İşlem tamamlanamadı. Daha sonra tekrar deneyin.");
    }
  }

  const sortedBenchmarkRuns = useMemo(() => sortBenchmarkRuns(benchmarkRuns), [benchmarkRuns]);
  const latestRun = sortedBenchmarkRuns[0];

  return (
    <section className="operations-grid research-knowledge-page">
      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Bilgi havuzu</h2>
            <span>Ürün ve hizmet bilgileri, kaynaklar ve müşavir kararları burada tutulur.</span>
          </div>
          <button className="secondary" onClick={() => void loadResearchData()} type="button">Kayıtları yenile</button>
        </div>
        <div className="summary-grid compact">
          <Metric label="Kayıt" value={profiles.length} />
          <Metric label="Kalite ölçümü" value={benchmarkRuns.length} />
        </div>
        <p className={status.includes("alınamadı") || status.includes("tamamlanamadı") ? "decision-status error" : "decision-status"}>{status || "Yeni belgelerde kaynaklı bilgi kullanılır. Fiş yine müşavir kontrolünden geçer."}</p>
      </div>

      <div className="panel">
        <h2>Araştırma kayıtları</h2>
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
            <p className="decision-status">Araştırma sonucu oluştuğunda burada görünür.</p>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>Seçilen kayıt</h2>
        <Info label="Anahtar" value={selectedProfile?.key || ""} />
        <Info label="Kategori" value={categorySummary(selectedProfile)} />
        <Info label="Kaynak güveni" value={formatConfidence(profileResearchConfidence(selectedProfile))} />
        <Info label="Fiş kararına etkisi" value={formatConfidence(profileImpactConfidence(selectedProfile))} />
        <Info label="Neden kontrol gerekiyor?" value={reviewReason(selectedProfile)} />
        <Info label="Kaynak" value={selectedProfile ? sourceSummary(selectedProfile) : ""} />
        <Info label="Durum" value={selectedProfile?.override ? "Müşavir kararı" : selectedProfile?.status || "Kayıtlı"} />
        <p className="research-help">Kaynak güveni düşükse sistem fiş kararını müşavir kontrolüne bırakır.</p>
        <input
          aria-label="Araştırma sorgusu"
          className="research-field"
          disabled={!selectedProfile}
          onChange={(event) => setRefreshQuery(event.target.value)}
          placeholder="Ürün/marka + tedarikçi"
          value={refreshQuery}
        />
        <button
          className="secondary"
          disabled={!selectedProfile}
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
          Araştırmayı yenile
        </button>
      </div>

      <div className="panel">
        <h2>Müşavir kararı</h2>
        <p className="research-help">Seçilen kayıt için ofis kararınızı saklayın.</p>
        <input
          aria-label="Override kategori"
          className="research-field"
          onChange={(event) => setOverrideCategory(event.target.value)}
          placeholder="Kategori"
          value={overrideCategory}
        />
        <textarea
          aria-label="Override özeti"
          className="research-field"
          onChange={(event) => setOverrideSummary(event.target.value)}
          placeholder="Müşavir kararını yazın"
          rows={4}
          value={overrideSummary}
        />
        <button className="primary" disabled={!selectedProfile} onClick={() => void submitOverride()} type="button">
          Müşavir kararını kaydet
        </button>
      </div>

      <div className="panel">
        <div className="panel-heading">
          <div>
            <h2>Kalite ölçümü</h2>
            <span>Örnek kayıtlarla eşleşme kalitesini gösterir.</span>
          </div>
          <button className="secondary" onClick={() => void submitBenchmark()} type="button">Kalite ölçümünü çalıştır</button>
        </div>
        <Info label="Son ölçüm doğruluğu" value={formatRunAccuracy(latestRun?.accuracy)} />
        <Info label="Örnek sayısı" value={latestRun?.case_count ? String(latestRun.case_count) : ""} />
        <Info label="Marka / ürün" value={formatRunAccuracy(latestRun?.metrics?.brand_accuracy)} />
        <Info label="Kategori" value={formatRunAccuracy(latestRun?.metrics?.category_accuracy)} />
        <Info label="Fiş kararına etkisi" value={formatRunAccuracy(latestRun?.metrics?.accounting_impact_accuracy)} />
        <Info label="Kontrole ayırma doğruluğu" value={formatRunAccuracy(latestRun?.metrics?.review_gate_accuracy)} />
        <p className="decision-status">
          Bu ölçüm canlı model çağırmaz; araştırma kayıtları ve müşavir kararlarını ölçer.
        </p>
        <div className="basket-list">
          {sortedBenchmarkRuns.length ? sortedBenchmarkRuns.slice(0, 5).map((run) => (
            <div className="basket-row" key={run.run_id || run.created_at}>
              <div>
                <strong>{benchmarkRunTime(run)}</strong>
                <span>{run.passed_count ?? run.matched_count ?? 0}/{run.case_count || 0} araştırma kaydı eşleşmesi</span>
              </div>
              <span className="status export_added">{formatRunAccuracy(run.accuracy)}</span>
            </div>
          )) : (
            <div className="basket-row">
              <div>
                <strong>Henüz kalite ölçümü yok</strong>
                <span>Araştırma veya müşavir kararı sonrası kalite ölçümünü çalıştırın.</span>
              </div>
              <span className="status queued">Bekliyor</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
