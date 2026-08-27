export type WorkState = 'empty' | 'draft' | 'running' | 'paused' | 'stopped' | 'completed' | 'limit_reached' | 'waiting_limit' | 'needs_attention' | 'requires_login'

export interface Account {
  id: number
  vk_user_id: number
  first_name: string
  last_name: string
  display_name: string
  profile_url: string
  avatar_url: string
  note: string
  enabled: boolean
  auth_status: string
  api_status: string
  session_status: string
  work_status: string
  health_status?: 'alive' | 'blocked' | 'deactivated' | 'requires_login' | 'unknown'
  health_checked_at?: string | null
  health_detail?: string
  assigned_groups: number
  processed_count: number
  success_count: number
  failed_count: number
  unread_count: number
  last_checked_at: string | null
  last_action_at: string | null
  last_error: string
  daily_limit?: number
  quota_consumed?: number
  quota_available?: number
  quota_window_started_at?: string | null
  quota_window_ends_at?: string | null
}

export interface Dashboard {
  work_state: WorkState
  metrics: {
    active_accounts: number
    remaining: number
    processing: number
    success: number
    failed: number
    unread: number
  }
  events: Array<{ id: number; time: string; level: string; message: string }>
}

export interface WorkItem {
  id: number
  group_name: string
  url: string
  state: string
  account: string
  attempts: number
  last_error: string
}

export interface ResultItem {
  id: number
  run_id: number
  work_item_id: number
  group_name: string
  url: string
  message_state: string
  message_reason: string
  suggested_state: string
  suggested_reason: string
  destination: string
  account: string
  completed_at: string | null
}

export interface WorkHistory {
  id: number
  run_id: number
  group_name: string
  url: string
  vk_id: number
  state: string
  account: string
  attempts_count: number
  started_at: string | null
  completed_at: string | null
  last_error: string
  result: null | {
    message_state: string
    message_reason: string
    suggested_state: string
    suggested_reason: string
    outcome: string
    destination: string
  }
  attempts: Array<{
    id: number
    direction: string
    state: string
    vk_object_id: number | null
    error_code: number | null
    error_class: string
    reason: string
    technical: object
    created_at: string
  }>
  events: Array<{ id: number; created_at: string; level: string; message: string; technical: object }>
}

export interface Dialog {
  id: number
  account_id: number
  account_name: string
  peer_id: number
  title: string
  avatar_url: string
  unread_count: number
  can_write?: boolean
  write_disabled_reason?: string
  last_message_at: string | null
  last_message_preview?: string
  last_message_outgoing?: boolean
  last_message_deleted?: boolean
  is_pinned?: boolean
  pinned_at?: string | null
  is_archived?: boolean
  archived_at?: string | null
  folder_ids?: number[]
}

export interface DialogFolder {
  id: number
  account_id: number
  name: string
  dialogs_count: number
}

export interface ReplyAccount {
  id: number
  name: string
  note: string
  avatar_url: string
}

export interface MessageAttachment {
  type: string
  [key: string]: unknown
}

export interface NestedMessage {
  id?: number
  conversation_message_id?: number
  from_id?: number
  text?: string
  date?: number
  attachments?: MessageAttachment[]
  fwd_messages?: NestedMessage[]
}

export interface MessageItem {
  id: number
  vk_message_id: number
  conversation_message_id?: number | null
  from_id: number
  outgoing: boolean
  body: string
  sent_at: string
  updated_at?: string | null
  is_read: boolean
  deleted?: boolean
  attachments?: MessageAttachment[]
  reply_message?: NestedMessage | null
  forwarded_messages?: NestedMessage[]
  reactions?: unknown[] | Record<string, unknown>
  raw_meta?: Record<string, unknown>
}

export interface MessagePayload {
  dialog: Dialog & { can_write: boolean; write_disabled_reason: string }
  reply_account: ReplyAccount
  messages: MessageItem[]
  local_total: number
  has_older_local: boolean
  next_before_vk_message_id: number | null
}

export interface RunSummary {
  id: number
  state: string
  started_at: string | null
  finished_at: string | null
  original_count: number
  processed_count: number
  success_count: number
  failure_count: number
}

export interface RunHistoryPayload {
  current_run_id: number | null
  items: RunSummary[]
}
