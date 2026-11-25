/**
 * Example: a generic OpenAI-compatible local server as a pi provider, with a live model list.
 *
 * Shape follows the documented createProvider form in pi's extensions.md and custom-provider.md
 * (installed docs, pi 1.5.2). It is a template, not a tested integration: it has not been compiled
 * or run against a server. Check every name with check_extension_names.py before relying on it.
 *
 * Put this file in ~/.pi/agent/extensions/ (global) or .pi/extensions/ (project, after trust).
 * Run /reload after a change, or start pi with -e <path> to test it on its own.
 */

import { createProvider, openAICompletionsApi } from "@earendil-works/pi-ai/compat";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Keep /v1 in the URL. pi appends /chat/completions and /models to the base URL, so a URL
// without /v1 fails on both. Use the server's own address, not a LAN address in shared code.
const BASE_URL = (process.env.LOCAL_LLM_BASE_URL ?? "http://127.0.0.1:8080/v1").replace(/\/$/, "");

// Read the key from the environment of the process that starts pi, or use a placeholder when the
// server has no authentication. Never put a real key in this file.
const ENV_KEY = process.env.LOCAL_LLM_API_KEY;

interface ServerModel {
	id: string;
	loaded?: boolean;
	context_window?: number;
	max_output_tokens?: number;
}

interface ModelsResponse {
	data?: ServerModel[];
}

async function failure(response: Response): Promise<Error> {
	// Include the status and a bounded body. Do not log headers: they can carry credentials.
	const body = (await response.text()).slice(0, 300);
	return new Error(`GET /models failed: ${response.status} ${response.statusText}${body ? ` - ${body}` : ""}`);
}

export default function (pi: ExtensionAPI) {
	pi.registerProvider(
		createProvider({
			id: "local-llm",
			name: "Local LLM",
			baseUrl: BASE_URL,
			api: openAICompletionsApi(),
			auth: {
				apiKey: {
					name: "Local LLM key",
					async login(interaction) {
						return {
							type: "api_key",
							key: await interaction.prompt({ type: "secret", message: "API key (any text if none is set)" }),
						};
					},
					async resolve({ credential }) {
						const key = credential?.key ?? ENV_KEY ?? "local";
						return { auth: { apiKey: key }, source: credential?.key ? "stored API key" : "environment or placeholder" };
					},
				},
			},
			// No static catalogue. The live list below replaces it on each refresh, so /model shows
			// what the server serves now.
			models: [],
			async fetchModels({ signal, credential }) {
				const key = credential?.type === "api_key" ? credential.key : ENV_KEY ?? "local";
				const response = await fetch(`${BASE_URL}/models`, {
					signal,
					headers: { Authorization: `Bearer ${key}` },
				});
				if (!response.ok) throw await failure(response);

				const payload = (await response.json()) as ModelsResponse;
				if (!Array.isArray(payload.data)) throw new Error("GET /models returned no model list");

				// Some servers list models they can load but do not serve. Calling chat for those
				// fails at request time, so keep only the models marked as loaded. If the server has
				// no such flag, remove this filter and say so in the report.
				return payload.data
					.filter((model) => model.loaded !== false)
					.map((model) => ({
						id: model.id,
						provider: "local-llm",
						api: "openai-completions",
						baseUrl: BASE_URL,
						name: model.id,
						reasoning: false,
						input: ["text"],
						cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
						contextWindow: model.context_window ?? 128000,
						maxTokens: model.max_output_tokens ?? 16384,
						compat: {
							// Set explicitly. pi detects compatibility from the URL, and an unknown local
							// host gets the defaults for no particular server.
							maxTokensField: "max_tokens",
							supportsDeveloperRole: false,
							supportsUsageInStreaming: true,
						},
					}));
			},
		}),
	);
}
