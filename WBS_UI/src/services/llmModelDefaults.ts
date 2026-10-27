import type { ModelSettings } from './llmApi';

export const defaultModelSettings: ModelSettings = {
  context_tokens: 8192, output_tokens: 512, temperature: null, output_mode: 'validated_json',
  tool_mode: 'none', concurrency: 1, timeout_seconds: 60, max_calls: 20,
  max_total_tokens: 100000, max_cost_usd: null, options: { compatible_token_parameter: 'max_tokens' },
  retry: { max_attempts: 3, allow_format_repair: true, retry_statuses: [429],
    retry_before_submit: true, retry_ambiguous_submission: false,
    base_delay_seconds: .25, max_delay_seconds: 5 }, allowed_workflows: ['summary'],
};
