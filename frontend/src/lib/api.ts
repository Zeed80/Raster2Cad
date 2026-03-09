export const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "/api";
export const backendBaseUrl = apiBaseUrl.replace(/\/api$/, "");

export type ProviderType = "vllm" | "ollama";
export type JobMode = "copy" | "isometry";
export type DrawingDomain = "auto" | "piping" | "vessels" | "parts" | "general";
export type OutputFormat = "dxf" | "dwg";
export type ViewPreset = "iso-ne" | "iso-nw" | "iso-se" | "iso-sw" | "top-front-right";

export interface ModelRuntimeHints {
  num_ctx: number;
  num_predict: number;
  keep_alive?: string | null;
  rationale?: string | null;
}

export interface ModelRuntimeOptions {
  auto_tune: boolean;
  num_ctx?: number | null;
  num_predict?: number | null;
  keep_alive?: string | null;
}

export interface ModelDescriptor {
  id: string;
  display_name: string;
  provider: ProviderType;
  recommended: boolean;
  summary?: string | null;
  details?: Record<string, unknown>;
  runtime_hints?: ModelRuntimeHints | null;
  capabilities: {
    vision: boolean;
    reasoning: boolean;
    tool_calling: boolean;
    structured_json: boolean;
    role_fit: string[];
  };
}

export interface ClarificationPrompt {
  prompt_id: string;
  question: string;
  options: Array<{ id: string; label: string; description?: string | null }>;
}

export interface JobRecord {
  job_id: string;
  filename: string;
  mode: JobMode;
  domain: DrawingDomain;
  output_format: OutputFormat;
  model_id: string;
  provider: ProviderType;
  runtime_options: ModelRuntimeOptions;
  resolved_models: Record<string, string>;
  status: "queued" | "running" | "needs_input" | "done" | "failed";
  stage: string;
  confidence: number;
  error?: string | null;
  critic_findings: string[];
  clarification?: ClarificationPrompt | null;
  artifacts: {
    drawing_path?: string | null;
    dwg_path?: string | null;
    isometric_path?: string | null;
    scene_graph_path?: string | null;
    report_path?: string | null;
    diff_path?: string | null;
    source_preview_path?: string | null;
    overlay_preview_path?: string | null;
  };
  scene_graph?: {
    domain: DrawingDomain;
    objects: Array<{ object_id: string; kind: string; label: string; confidence: number }>;
    texts: Array<{ text_id: string; content: string }>;
    dimensions: Array<{ dimension_id: string; label: string; value: string }>;
    notes: string[];
  } | null;
  chat_history: Array<{ timestamp: string; message: string; applied: boolean; summary?: string | null }>;
  iso_view: {
    preset: ViewPreset;
    rotate_x: number;
    rotate_y: number;
    rotate_z: number;
    scale: number;
    explode_spacing: number;
    annotation_density: number;
  };
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchModels(): Promise<ModelDescriptor[]> {
  const response = await fetch(`${apiBaseUrl}/models`);
  const payload = await readJson<{ models: ModelDescriptor[] }>(response);
  return payload.models;
}

export async function createJob(input: {
  file: File;
  mode: JobMode;
  domain: DrawingDomain;
  outputFormat: OutputFormat;
  modelId: string;
  provider: ProviderType;
  runtimeOptions: ModelRuntimeOptions;
  isoView: JobRecord["iso_view"];
}): Promise<JobRecord> {
  const form = new FormData();
  form.set("file", input.file);
  form.set("mode", input.mode);
  form.set("domain", input.domain);
  form.set("output_format", input.outputFormat);
  form.set("model_id", input.modelId);
  form.set("provider", input.provider);
  form.set("auto_tune", String(input.runtimeOptions.auto_tune));
  if (typeof input.runtimeOptions.num_ctx === "number") {
    form.set("num_ctx", String(input.runtimeOptions.num_ctx));
  }
  if (typeof input.runtimeOptions.num_predict === "number") {
    form.set("num_predict", String(input.runtimeOptions.num_predict));
  }
  if (input.runtimeOptions.keep_alive) {
    form.set("keep_alive", input.runtimeOptions.keep_alive);
  }
  form.set("iso_preset", input.isoView.preset);
  form.set("rotate_x", String(input.isoView.rotate_x));
  form.set("rotate_y", String(input.isoView.rotate_y));
  form.set("rotate_z", String(input.isoView.rotate_z));
  form.set("scale", String(input.isoView.scale));
  form.set("explode_spacing", String(input.isoView.explode_spacing));
  form.set("annotation_density", String(input.isoView.annotation_density));
  const response = await fetch(`${apiBaseUrl}/jobs`, { method: "POST", body: form });
  return readJson<JobRecord>(response);
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const response = await fetch(`${apiBaseUrl}/jobs/${jobId}`);
  return readJson<JobRecord>(response);
}

export async function answerClarification(jobId: string, optionId: string): Promise<JobRecord> {
  const response = await fetch(`${apiBaseUrl}/jobs/${jobId}/clarification`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ option_id: optionId }),
  });
  return readJson<JobRecord>(response);
}

export async function sendChatEdit(jobId: string, message: string): Promise<JobRecord> {
  const response = await fetch(`${apiBaseUrl}/jobs/${jobId}/chat-edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  return readJson<JobRecord>(response);
}

export async function patchView(jobId: string, isoView: JobRecord["iso_view"]): Promise<JobRecord> {
  const response = await fetch(`${apiBaseUrl}/jobs/${jobId}/view`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ iso_view: isoView }),
  });
  return readJson<JobRecord>(response);
}
