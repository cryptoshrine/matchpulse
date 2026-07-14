/**
 * API type definitions matching backend Pydantic schemas.
 *
 * These types must exactly match the backend schemas in:
 * - app/chat/schemas.py
 * - app/shared/schemas.py
 */

// WebSocket message types (from app/chat/schemas.py)
export type WebSocketMessageType = 'message' | 'ping';
export type WebSocketResponseType = 'text' | 'tool_status' | 'done' | 'error' | 'pong' | 'artifact' | 'live_update' | 'schedule_update';
export type ToolStatus = 'started' | 'completed' | 'failed';

// Live match notification types (Phase 8.8.1)
export type LiveNotificationType =
  | 'goal'
  | 'card'
  | 'penalty'
  | 'var'
  | 'halftime'
  | 'fulltime'
  | 'tactical_shift'
  | 'momentum_shift'
  | 'event_amendment';

export interface LiveNotification {
  notification_type: LiveNotificationType;
  match_id: number;
  message: string;
  event_id?: string | null;
  timestamp: string;
  // Goal-specific fields
  player_name?: string;
  team_name?: string;
  minute?: number;
  xg?: number;
  home_score?: number;
  away_score?: number;
  // Card-specific fields
  card_color?: 'yellow' | 'red';
  // Halftime/Fulltime fields
  home_team?: string;
  away_team?: string;
  home_xg?: number;
  away_xg?: number;
  // Tactical-shift fields
  shift_type?: string;
  confidence?: number;
  previous_value?: string | null;
  new_value?: string | null;
  explanation?: string | null;
  // Momentum-shift fields
  momentum_delta?: number;
  contributing_events?: number;
  // Provider-revision amendment fields
  amendment_type?: 'goal_attribution';
  amends_event_id?: string;
}

export interface LiveMatchState {
  match_id: number;
  home_team: string;
  away_team: string;
  home_team_id: number;
  away_team_id: number;
  home_score: number;
  away_score: number;
  minute: number;
  period: number;
  status: string;
  home_xg: number;
  away_xg: number;
  source: string;
  last_event_id?: string | null;
  last_updated?: string | null;
}

export interface WebSocketMessageRequest {
  type: WebSocketMessageType;
  content?: string | null;
  metadata?: Record<string, string> | null;
}

export interface ArtifactData {
  id?: string;  // DB primary key (added by backend after persistence)
  viz_id: string;
  match_id: number;
  viz_type: string;
  file_path: string;
  file_size_bytes: number;
  dimensions: [number, number];
  format: string;
  created_at: string;
  duration_seconds?: number | null;
  fps?: number | null;
}

export interface WebSocketMessageResponse {
  type: WebSocketResponseType;
  content?: string | null;
  tool_name?: string | null;
  status?: ToolStatus | null;
  usage?: {
    total_tokens: number;
    input_tokens: number;
    output_tokens: number;
  } | null;
  error?: string | null;
  detail?: string | null;
  artifacts?: ArtifactData[] | null;
  live_notification?: LiveNotification | null;  // Phase 8.8.1: Live match updates
  timestamp: string;
}

// Shared response types (from app/shared/schemas.py)
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ErrorResponse {
  error: string;
  detail?: string | null;
  type?: string | null;
}

// Conversation types (from app/chat/schemas.py)
export type AgentMode = 'tactical' | 'performance' | 'animation' | 'social_media' | 'quick_insights';

export interface Conversation {
  id: string;
  user_id: string;
  project_id: string | null;
  title: string;
  agent_mode: AgentMode;
  match_id: number | null;
  teams: Record<string, string> | null;
  competition: string | null;
  match_date: string | null;
  is_archived: boolean;
  is_pinned: boolean;
  message_count: number;
  visualization_count: number;
  animation_count: number;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  live_context?: {  // Phase 8.8.1: Live match following context
    match_id: number;
    started_at: string;
    home_team: string;
    away_team: string;
    auto_notify: boolean;
  } | null;
}

export interface ConversationCreate {
  title: string;
  agent_mode?: AgentMode;
  project_id?: string;
  match_id?: number;
  teams?: Record<string, string>;
  competition?: string;
  match_date?: string;
}

export interface ConversationUpdate {
  title?: string;
  agent_mode?: AgentMode;
  match_id?: number;
  teams?: Record<string, string>;
  competition?: string;
  match_date?: string;
  is_archived?: boolean;
  is_pinned?: boolean;
  live_context?: {  // Phase 8.8.2: Clear live context by setting to null
    match_id: number;
    started_at: string;
    home_team: string;
    away_team: string;
    auto_notify: boolean;
  } | null;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
  page: number;
  page_size: number;
}

// Message types
export type MessageRole = 'user' | 'assistant' | 'system';

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  sequence_number: number;
  created_at: string;
  updated_at: string;
  edited_at: string | null;
  tokens: number;
  finish_reason: string | null;
  tool_calls: Record<string, unknown>[] | null;
}

export interface MessageCreate {
  content: string;
  role?: MessageRole;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
}

// Phase 8.9: Scheduling types
export interface UpcomingMatch {
  match_id: number;
  home_team: string;
  away_team: string;
  match_date: string;
  competition: string;
  competition_id: number;
  season_id: number;
  can_schedule: boolean;
}

export interface UpcomingMatchesResponse {
  matches: UpcomingMatch[];
  match_count: number;
  days_ahead: number;
  filters_applied: Record<string, string>;
}

export interface ScheduledMatch {
  schedule_id: string;
  match_id: number;
  home_team: string;
  away_team: string;
  match_date: string;
  competition: string;
  auto_follow_enabled: boolean;
  is_active: boolean;
  scheduled_at: string;
}

export interface ScheduledMatchListResponse {
  scheduled_matches: ScheduledMatch[];
  total: number;
}

export interface ScheduleMatchRequest {
  match_id: number;
  auto_follow_enabled?: boolean;
  notify_before?: boolean;
  notify_kickoff?: boolean;
  conversation_id?: string;
}

export interface CancelScheduleResponse {
  schedule_id: string;
  match_id: number;
  cancelled: boolean;
  message: string;
}

export type ScheduleUpdateType = 'match_scheduled' | 'match_starting' | 'match_cancelled';

export interface ScheduleUpdate {
  update_type: ScheduleUpdateType;
  match_id: number;
  match_info?: ScheduledMatch;
  timestamp: string;
}
