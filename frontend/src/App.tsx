import { FormEvent, useEffect, useState } from "react";

import {
  answerClarification,
  apiBaseUrl,
  backendBaseUrl,
  createJob,
  fetchModels,
  getJob,
  ModelDescriptor,
  ModelRuntimeOptions,
  patchView,
  sendChatEdit,
  JobMode,
  DrawingDomain,
  OutputFormat,
  JobRecord,
  ViewPreset,
} from "./lib/api";

const defaultIsoView: JobRecord["iso_view"] = {
  preset: "iso-ne",
  rotate_x: 35.264,
  rotate_y: 45,
  rotate_z: 0,
  scale: 1,
  explode_spacing: 12,
  annotation_density: 0.5,
};

const domainOptions: Array<{ value: DrawingDomain; label: string }> = [
  { value: "auto", label: "РђРІС‚Рѕ" },
  { value: "piping", label: "РўСЂСѓР±РѕРїСЂРѕРІРѕРґС‹" },
  { value: "vessels", label: "РЎРѕСЃСѓРґС‹ Рё РµРјРєРѕСЃС‚Рё" },
  { value: "parts", label: "Р”РµС‚Р°Р»Рё Рё СЌР»РµРјРµРЅС‚С‹" },
  { value: "general", label: "РћР±С‰РёР№ С‡РµСЂС‚РµР¶" },
];

const viewOptions: Array<{ value: ViewPreset; label: string }> = [
  { value: "iso-ne", label: "ISO NE" },
  { value: "iso-nw", label: "ISO NW" },
  { value: "iso-se", label: "ISO SE" },
  { value: "iso-sw", label: "ISO SW" },
  { value: "top-front-right", label: "Top Front Right" },
];

type RuntimeFormState = {
  autoTune: boolean;
  numCtx: string;
  numPredict: string;
  keepAlive: string;
};

function runtimeStateFromModel(model: ModelDescriptor | null): RuntimeFormState {
  return {
    autoTune: true,
    numCtx: model?.runtime_hints?.num_ctx ? String(model.runtime_hints.num_ctx) : "",
    numPredict: model?.runtime_hints?.num_predict ? String(model.runtime_hints.num_predict) : "",
    keepAlive: model?.runtime_hints?.keep_alive ?? "",
  };
}

function parsePositiveInt(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return undefined;
  }
  return parsed;
}

function App() {
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<JobMode>("copy");
  const [domain, setDomain] = useState<DrawingDomain>("auto");
  const [outputFormat, setOutputFormat] = useState<OutputFormat>("dxf");
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [selectedProvider, setSelectedProvider] = useState<"vllm" | "ollama">("ollama");
  const [isoView, setIsoView] = useState(defaultIsoView);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [chatMessage, setChatMessage] = useState("");
  const [runtimeForm, setRuntimeForm] = useState<RuntimeFormState>(runtimeStateFromModel(null));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void loadModels();
  }, []);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) {
      return;
    }

    const timer = window.setInterval(() => {
      void getJob(job.job_id)
        .then(setJob)
        .catch((err: Error) => setError(err.message));
    }, 2500);

    return () => window.clearInterval(timer);
  }, [job]);

  async function loadModels() {
    try {
      const result = await fetchModels();
      setModels(result);
      if (result.length > 0) {
        const preferred = result.find((item) => item.recommended) ?? result[0];
        setSelectedModel(preferred.id);
        setSelectedProvider(preferred.provider);
        setRuntimeForm(runtimeStateFromModel(preferred));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ РјРѕРґРµР»Рё");
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file || !selectedModel) {
      setError("РќСѓР¶РЅС‹ С„Р°Р№Р» Рё РјРѕРґРµР»СЊ.");
      return;
    }
    const runtimeOptions: ModelRuntimeOptions = {
      auto_tune: runtimeForm.autoTune,
      num_ctx: parsePositiveInt(runtimeForm.numCtx),
      num_predict: parsePositiveInt(runtimeForm.numPredict),
      keep_alive: runtimeForm.keepAlive.trim() || undefined,
    };
    if (selectedProvider === "ollama" && runtimeForm.numCtx.trim() && runtimeOptions.num_ctx === undefined) {
      setError("num_ctx must be a positive integer.");
      return;
    }
    if (selectedProvider === "ollama" && runtimeForm.numPredict.trim() && runtimeOptions.num_predict === undefined) {
      setError("num_predict must be a positive integer.");
      return;
    }

    try {
      setBusy(true);
      setError("");
      const nextJob = await createJob({
        file,
        mode,
        domain,
        outputFormat,
        modelId: selectedModel,
        provider: selectedProvider,
        runtimeOptions,
        isoView,
      });
      setJob(nextJob);
    } catch (err) {
      setError(err instanceof Error ? err.message : "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ job.");
    } finally {
      setBusy(false);
    }
  }

  const providerModels = models.filter((item) => item.provider === selectedProvider);
  const selectedModelMeta = providerModels.find((item) => item.id === selectedModel) ?? null;
  const runtimeHint = selectedProvider === "ollama" ? selectedModelMeta?.runtime_hints ?? null : null;

  useEffect(() => {
    if (!runtimeForm.autoTune || selectedProvider !== "ollama") {
      return;
    }
    const next = runtimeStateFromModel(selectedModelMeta);
    setRuntimeForm((current) => (
      current.autoTune === next.autoTune &&
      current.numCtx === next.numCtx &&
      current.numPredict === next.numPredict &&
      current.keepAlive === next.keepAlive
    ) ? current : next);
  }, [runtimeForm.autoTune, selectedProvider, selectedModelMeta]);

  function updateRuntimeField(field: "numCtx" | "numPredict" | "keepAlive", value: string) {
    setRuntimeForm((current) => ({ ...current, autoTune: false, [field]: value }));
  }

  function applyAutoRuntime(model: ModelDescriptor | null) {
    setRuntimeForm(runtimeStateFromModel(model));
  }

  function artifactUrl(path?: string | null) {
    return path ? `${backendBaseUrl}${path}` : null;
  }

  return (
    <div className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Raster2Cad Agent</p>
          <h1>РњСѓР»СЊС‚РёРјРѕРґР°Р»СЊРЅС‹Р№ CAD rebuild Р±РµР· OCR Рё Р±РµР· СЂСѓС‡РЅРѕР№ С‚СЂР°СЃСЃРёСЂРѕРІРєРё</h1>
          <p className="hero-copy">
            Р РµР¶РёРјС‹ <strong>РўРѕС‡РЅР°СЏ РєРѕРїРёСЏ</strong> Рё <strong>РР·РѕРјРµС‚СЂРёСЏ</strong>, РІС‹Р±РѕСЂ РјРѕРґРµР»РµР№ РёР·
            РµРґРёРЅРѕРіРѕ РєР°С‚Р°Р»РѕРіР° <code>vLLM + Ollama</code>, СѓС‚РѕС‡РЅРµРЅРёСЏ РїРѕ confidence Рё patch-СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ С‡РµСЂРµР· С‡Р°С‚.
          </p>
        </div>
        <div className="hero-card">
          <span>API</span>
          <strong>{apiBaseUrl}</strong>
          <span>РњРѕРґРµР»РµР№ РІ РєР°С‚Р°Р»РѕРіРµ: {models.length}</span>
          <span>Primary runtime: external or native Ollama</span>
        </div>
      </section>

      <div className="grid">
        <form className="panel form-panel" onSubmit={onSubmit}>
          <div className="panel-header">
            <h2>РќРѕРІС‹Р№ job</h2>
            <span className="badge">{busy ? "Р—Р°РїСѓСЃРє..." : "Ready"}</span>
          </div>

          <div className="mode-switch">
            <button
              className={mode === "copy" ? "mode active" : "mode"}
              type="button"
              onClick={() => setMode("copy")}
            >
              РўРѕС‡РЅР°СЏ РєРѕРїРёСЏ
            </button>
            <button
              className={mode === "isometry" ? "mode active" : "mode"}
              type="button"
              onClick={() => setMode("isometry")}
            >
              РР·РѕРјРµС‚СЂРёСЏ
            </button>
          </div>

          <label className="field">
            <span>Р¤Р°Р№Р»</span>
            <input type="file" accept=".png,.jpg,.jpeg,.tif,.tiff,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>

          <div className="two-col">
            <label className="field">
              <span>Р”РѕРјРµРЅ</span>
              <select value={domain} onChange={(event) => setDomain(event.target.value as DrawingDomain)}>
                {domainOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Р¤РѕСЂРјР°С‚</span>
              <select value={outputFormat} onChange={(event) => setOutputFormat(event.target.value as OutputFormat)}>
                <option value="dxf">DXF</option>
                <option value="dwg">DWG</option>
              </select>
            </label>
          </div>

          <div className="two-col">
            <label className="field">
              <span>Provider</span>
              <select
                value={selectedProvider}
                onChange={(event) => {
                  const provider = event.target.value as "vllm" | "ollama";
                  const currentModelExists = models.some((item) => item.provider === provider && item.id === selectedModel);
                  const replacement = currentModelExists ? models.find((item) => item.provider === provider && item.id === selectedModel) ?? null : models.find((item) => item.provider === provider) ?? null;
                  setSelectedProvider(provider);
                  if (replacement && !currentModelExists) {
                    setSelectedModel(replacement.id);
                  }
                  if (provider === "ollama" && runtimeForm.autoTune) {
                    applyAutoRuntime(replacement);
                  }
                }}
              >
                <option value="vllm">vLLM</option>
                <option value="ollama">Ollama</option>
              </select>
            </label>

            <label className="field">
              <span>РњРѕРґРµР»СЊ</span>
              <input
                list={`models-${selectedProvider}`}
                value={selectedModel}
                onChange={(event) => {
                  const nextModelId = event.target.value;
                  setSelectedModel(nextModelId);
                  if (runtimeForm.autoTune && selectedProvider === "ollama") {
                    applyAutoRuntime(providerModels.find((model) => model.id === nextModelId) ?? null);
                  }
                }}
                placeholder={selectedProvider === "ollama" ? "Введите любой model id из Ollama" : "Введите model id"}
              />
              <datalist id={`models-${selectedProvider}`}>
                {providerModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name}
                  </option>
                ))}
              </datalist>
            </label>
          </div>

          {selectedModelMeta ? (
            <div className="model-meta">
              <strong>{selectedModelMeta.display_name}</strong>
              <span>{selectedModelMeta.summary ?? "No summary available."}</span>
              <div className="chip-row">
                <span className={selectedModelMeta.capabilities.vision ? "chip active" : "chip"}>vision</span>
                <span className={selectedModelMeta.capabilities.reasoning ? "chip active" : "chip"}>reasoning</span>
                <span className={selectedModelMeta.capabilities.structured_json ? "chip active" : "chip"}>json</span>
              </div>
            </div>
          ) : null}

          {selectedProvider === "ollama" ? (
            <div className="model-meta">
              <strong>Ollama runtime</strong>
              <span>
                {runtimeForm.autoTune ? "Auto profile is active." : "Manual override is active."}
              </span>
              {runtimeHint?.rationale ? <span>{runtimeHint.rationale}</span> : null}
              <div className="two-col">
                <label className="field">
                  <span>num_ctx</span>
                  <input
                    type="number"
                    min="1024"
                    step="512"
                    value={runtimeForm.numCtx}
                    onChange={(event) => updateRuntimeField("numCtx", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>num_predict</span>
                  <input
                    type="number"
                    min="64"
                    step="64"
                    value={runtimeForm.numPredict}
                    onChange={(event) => updateRuntimeField("numPredict", event.target.value)}
                  />
                </label>
              </div>
              <div className="two-col">
                <label className="field">
                  <span>keep_alive</span>
                  <input
                    value={runtimeForm.keepAlive}
                    onChange={(event) => updateRuntimeField("keepAlive", event.target.value)}
                    placeholder="15m"
                  />
                </label>
                <label className="field">
                  <span>Mode</span>
                  <button
                    className="mode"
                    type="button"
                    onClick={() => applyAutoRuntime(selectedModelMeta)}
                  >
                    {runtimeForm.autoTune ? "Auto tuned" : "Reset to auto"}
                  </button>
                </label>
              </div>
              <span className="muted">
                Large Ollama models are safer with smaller context and output limits. Current values are sent with the job.
              </span>
            </div>
          ) : null}

          <div className="iso-block">
            <div className="panel-subtitle">РџР°СЂР°РјРµС‚СЂС‹ РёР·РѕРјРµС‚СЂРёРё</div>
            <div className="two-col">
              <label className="field">
                <span>Preset</span>
                <select
                  value={isoView.preset}
                  onChange={(event) => setIsoView((current) => ({ ...current, preset: event.target.value as ViewPreset }))}
                >
                  {viewOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Scale</span>
                <input
                  type="number"
                  step="0.1"
                  value={isoView.scale}
                  onChange={(event) => setIsoView((current) => ({ ...current, scale: Number(event.target.value) }))}
                />
              </label>
            </div>

            <div className="three-col">
              <label className="field">
                <span>Rotate X</span>
                <input
                  type="number"
                  step="0.1"
                  value={isoView.rotate_x}
                  onChange={(event) => setIsoView((current) => ({ ...current, rotate_x: Number(event.target.value) }))}
                />
              </label>
              <label className="field">
                <span>Rotate Y</span>
                <input
                  type="number"
                  step="0.1"
                  value={isoView.rotate_y}
                  onChange={(event) => setIsoView((current) => ({ ...current, rotate_y: Number(event.target.value) }))}
                />
              </label>
              <label className="field">
                <span>Rotate Z</span>
                <input
                  type="number"
                  step="0.1"
                  value={isoView.rotate_z}
                  onChange={(event) => setIsoView((current) => ({ ...current, rotate_z: Number(event.target.value) }))}
                />
              </label>
            </div>
          </div>

          {error ? <div className="error-box">{error}</div> : null}

          <button className="submit" type="submit" disabled={busy || !file || !selectedModel}>
            {busy ? "Р—Р°РїСѓСЃРє..." : "РЎРѕР·РґР°С‚СЊ job"}
          </button>
        </form>

        <section className="panel">
          <div className="panel-header">
            <h2>РўРµРєСѓС‰РёР№ job</h2>
            <span className={`badge badge-${job?.status ?? "idle"}`}>{job?.status ?? "idle"}</span>
          </div>

          {!job ? (
            <p className="muted">РџРѕСЃР»Рµ Р·Р°РїСѓСЃРєР° Р·РґРµСЃСЊ РїРѕСЏРІСЏС‚СЃСЏ СЃС‚Р°С‚СѓСЃ, confidence, Р°СЂС‚РµС„Р°РєС‚С‹ Рё С‚РѕС‡РєРё СѓС‚РѕС‡РЅРµРЅРёСЏ.</p>
          ) : (
            <>
              <div className="job-summary">
                <div>
                  <span>ID</span>
                  <strong>{job.job_id}</strong>
                </div>
                <div>
                  <span>Stage</span>
                  <strong>{job.stage}</strong>
                </div>
                <div>
                  <span>Confidence</span>
                  <strong>{job.confidence.toFixed(2)}</strong>
                </div>
                <div>
                  <span>Resolved domain</span>
                  <strong>{job.scene_graph?.domain ?? job.domain}</strong>
                </div>
                <div>
                  <span>Parser model</span>
                  <strong>{job.resolved_models.parser ?? job.model_id}</strong>
                </div>
                <div>
                  <span>Runtime</span>
                  <strong>
                    ctx {job.runtime_options.num_ctx ?? "auto"} / out {job.runtime_options.num_predict ?? "auto"}
                  </strong>
                </div>
              </div>

              {job.error ? <div className="error-box">{job.error}</div> : null}

              {job.clarification ? (
                <div className="clarification-box">
                  <h3>РќСѓР¶РЅРѕ СѓС‚РѕС‡РЅРµРЅРёРµ</h3>
                  <p>{job.clarification.question}</p>
                  <div className="option-list">
                    {job.clarification.options.map((option) => (
                      <button key={option.id} type="button" className="option" onClick={() => void answerClarification(job.job_id, option.id).then(setJob).catch((err: Error) => setError(err.message))}>
                        <strong>{option.label}</strong>
                        {option.description ? <span>{option.description}</span> : null}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="artifact-links">
                {Object.entries(job.artifacts)
                  .filter(([, value]) => Boolean(value))
                  .map(([key, value]) => (
                    <a key={key} href={artifactUrl(value) ?? "#"} target="_blank" rel="noreferrer">
                      {key}
                    </a>
                  ))}
              </div>

              {job.artifacts.source_preview_path ? (
                <div className="preview-grid">
                  <figure className="preview-card">
                    <img src={artifactUrl(job.artifacts.source_preview_path) ?? ""} alt="Source preview" />
                    <figcaption>Source preview</figcaption>
                  </figure>
                  {job.artifacts.overlay_preview_path ? (
                    <figure className="preview-card">
                      <img src={artifactUrl(job.artifacts.overlay_preview_path) ?? ""} alt="Overlay preview" />
                      <figcaption>Scene overlay</figcaption>
                    </figure>
                  ) : null}
                  {job.artifacts.diff_path ? (
                    <figure className="preview-card wide">
                      <img src={artifactUrl(job.artifacts.diff_path) ?? ""} alt="Diff preview" />
                      <figcaption>Source / overlay diff</figcaption>
                    </figure>
                  ) : null}
                </div>
              ) : null}

              <div className="panel-subtitle">Critic findings</div>
              <ul className="list">
                {job.critic_findings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>

              <div className="panel-subtitle">Objects</div>
              <div className="object-grid">
                {job.scene_graph?.objects.map((object) => (
                  <article key={object.object_id} className="object-card">
                    <strong>{object.label}</strong>
                    <span>{object.kind}</span>
                    <span>confidence {object.confidence.toFixed(2)}</span>
                  </article>
                ))}
              </div>

              <div className="panel-subtitle">Chat patch</div>
              <div className="chat-box">
                <input
                  value={chatMessage}
                  placeholder="РќР°РїСЂРёРјРµСЂ: СЌС‚Рѕ С„Р»Р°РЅРµС†, Р° РЅРµ РєР»Р°РїР°РЅ"
                  onChange={(event) => setChatMessage(event.target.value)}
                />
                <button
                  type="button"
                  onClick={() => {
                    if (!chatMessage.trim()) {
                      return;
                    }
                    void sendChatEdit(job.job_id, chatMessage)
                      .then((updated) => {
                        setJob(updated);
                        setChatMessage("");
                      })
                      .catch((err: Error) => setError(err.message));
                  }}
                >
                  РџСЂРёРјРµРЅРёС‚СЊ
                </button>
              </div>

              <div className="chat-history">
                {job.chat_history.map((item, index) => (
                  <div key={`${item.timestamp}-${index}`} className="chat-item">
                    <strong>{item.applied ? "Applied" : "Saved"}</strong>
                    <p>{item.message}</p>
                    {item.summary ? <span>{item.summary}</span> : null}
                  </div>
                ))}
              </div>

              {job.mode === "isometry" || job.artifacts.isometric_path ? (
                <div className="iso-controls">
                  <div className="panel-subtitle">Р‘С‹СЃС‚СЂР°СЏ СЃРјРµРЅР° РІРёРґР°</div>
                  <div className="option-list">
                    {viewOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className="option compact"
                        onClick={() => {
                          const nextView = { ...job.iso_view, preset: option.value };
                          void patchView(job.job_id, nextView)
                            .then(setJob)
                            .catch((err: Error) => setError(err.message));
                        }}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

export default App;
