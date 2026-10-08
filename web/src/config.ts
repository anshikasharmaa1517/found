/** Build-time settings. Values come from the CDK stack outputs (see .env.example). */

export interface AppConfig {
  region: string;
  userPoolId: string;
  userPoolClientId: string;
  apiUrl: string;
  wsUrl: string;
}

const KEYS: Record<keyof AppConfig, string> = {
  region: "VITE_REGION",
  userPoolId: "VITE_USER_POOL_ID",
  userPoolClientId: "VITE_USER_POOL_CLIENT_ID",
  apiUrl: "VITE_API_URL",
  wsUrl: "VITE_WS_URL",
};

export type ConfigResult = { ok: true; config: AppConfig } | { ok: false; missing: string[] };

export function readConfig(env: Record<string, string | undefined>): ConfigResult {
  const missing: string[] = [];
  const values: Partial<AppConfig> = {};
  for (const [field, key] of Object.entries(KEYS) as [keyof typeof KEYS, string][]) {
    const value = env[key]?.trim();
    if (value) values[field] = value;
    else missing.push(key);
  }
  if (missing.length > 0) return { ok: false, missing };
  const config = values as AppConfig;
  return { ok: true, config: { ...config, apiUrl: config.apiUrl.replace(/\/+$/, "") } };
}
