import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Inbox, MessageCircle, Paperclip, Pin, Plus, RefreshCcw, Search, Send, Smile, UserRound, X, Zap } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import EmojiPicker from '../components/EmojiPicker'
import MessageBubble from '../components/MessageBubble'
import { Button, EmptyState, PageHeader } from '../components/ui'
import type { Account, Dialog, DialogFolder, MessageItem, MessagePayload } from '../types'
import { formatLocalDate, formatLocalDateTime } from '../utils/time'

interface SyncDialogResult { ok: boolean; messages: number; fetched: number; total: number; next_offset: number; has_more: boolean; error?: string; state?: string }
interface SyncDialogRequest { dialogId: number; offset: number; count: number }
interface ReplyResult { ok: boolean; state?: string; message_id?: number | null; error?: string; account_id?: number }
interface QuickReply { id: string; text: string; created_at?: string; updated_at?: string }
interface MenuPoint<T> { value: T; x: number; y: number }
type InboxFilter = 'all' | 'unread' | 'archive'

function initialFilter(): InboxFilter {
  const value = new URLSearchParams(window.location.search).get('filter')
  return value === 'unread' || value === 'archive' ? value : 'all'
}

function lastMessagePreview(dialog: Dialog): string {
  const text = String(dialog.last_message_preview || '').trim()
  if (dialog.last_message_deleted) {
    if (dialog.last_message_outgoing) return 'Вы: Сообщение удалено'
    return text ? `Сообщение удалено · ${text}` : 'Сообщение удалено'
  }
  if (!text) return dialog.last_message_at ? 'Сообщение' : 'Нет сообщений'
  return dialog.last_message_outgoing ? `Вы: ${text}` : text
}

export default function InboxPage() {
  const client = useQueryClient()
  const [filter, setFilter] = useState<InboxFilter>(initialFilter)
  const [folderId, setFolderId] = useState<number | ''>('')
  const [accountId, setAccountId] = useState<number | ''>('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<number | null>(null)
  const [reply, setReply] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [renderedMessages, setRenderedMessages] = useState<MessageItem[]>([])
  const [beforeCursor, setBeforeCursor] = useState<number | null>(null)
  const [hasOlderLocal, setHasOlderLocal] = useState(false)
  const [remoteOffset, setRemoteOffset] = useState(0)
  const [hasMoreRemote, setHasMoreRemote] = useState(true)
  const [syncError, setSyncError] = useState('')
  const [showNewMessages, setShowNewMessages] = useState(false)
  const [activePopover, setActivePopover] = useState<'closed' | 'emoji' | 'quick'>('closed')
  const [quickText, setQuickText] = useState('')
  const [foldersCollapsed, setFoldersCollapsed] = useState(false)
  const [folderSearch, setFolderSearch] = useState('')
  const [folderCreateOpen, setFolderCreateOpen] = useState(false)
  const [folderCreateAccountId, setFolderCreateAccountId] = useState<number | ''>('')
  const [folderCreateName, setFolderCreateName] = useState('')
  const [draggingFolder, setDraggingFolder] = useState<number | null>(null)
  const [folderOrder, setFolderOrder] = useState<number[]>([])
  const [replyTarget, setReplyTarget] = useState<MessageItem | null>(null)
  const [dialogMenu, setDialogMenu] = useState<MenuPoint<Dialog> | null>(null)
  const [messageMenu, setMessageMenu] = useState<MenuPoint<MessageItem> | null>(null)
  const [forwardTarget, setForwardTarget] = useState<MessageItem | null>(null)
  const [messageSearchOpen, setMessageSearchOpen] = useState(false)
  const [messageSearch, setMessageSearch] = useState('')
  const [searchResults, setSearchResults] = useState<MessageItem[]>([])
  const [mediaOpen, setMediaOpen] = useState(false)
  const [mediaItems, setMediaItems] = useState<unknown[]>([])
  const messagesRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const loadingOlderRef = useRef(false)
  const isNearBottomRef = useRef(true)
  const renderedRef = useRef<MessageItem[]>([])
  const initialSyncRef = useRef<SyncDialogResult | null>(null)
  const initializedDialogRef = useRef<number | null>(null)
  const lastTypingRef = useRef(0)

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const suffix = new URLSearchParams({
    ...(accountId ? { account_id: String(accountId) } : {}),
    ...(filter === 'unread' ? { unread: 'true' } : {}),
    ...(filter !== 'archive' && folderId ? { folder_id: String(folderId) } : {}),
    ...(search ? { search } : {}),
  }).toString()
  const archiveSuffix = new URLSearchParams({
    ...(accountId ? { account_id: String(accountId) } : {}),
    ...(search ? { search } : {}),
  }).toString()
  const dialogs = useQuery({
    queryKey: ['dialogs', filter, accountId, folderId, search],
    queryFn: () => api<Dialog[]>(filter === 'archive' ? `/inbox/archive?${archiveSuffix}` : `/inbox/dialogs?${suffix}`),
    refetchInterval: 5000,
  })
  const folders = useQuery({ queryKey: ['dialog-folders', accountId], queryFn: () => api<DialogFolder[]>(`/inbox/folders${accountId ? `?account_id=${accountId}` : ''}`) })
  const messages = useQuery({ queryKey: ['dialog', selected], queryFn: () => api<MessagePayload>(`/inbox/dialogs/${selected}?limit=50`), enabled: selected != null, refetchInterval: selected != null ? 4000 : false })
  const quickReplies = useQuery({ queryKey: ['quick-replies'], queryFn: () => api<QuickReply[]>('/quick-replies'), enabled: activePopover === 'quick' })
  useEffect(() => { setFolderId('') }, [accountId])
  useEffect(() => { if (filter === 'archive') setFolderId('') }, [filter])

  const syncAccounts = useMutation({ mutationFn: (id: number) => api(`/inbox/sync?account_id=${id}`, { method: 'POST' }), onSuccess: () => client.invalidateQueries({ queryKey: ['dialogs'] }), onError: (error: Error) => toast.error(error.message) })
  const syncDialog = useMutation({
    mutationFn: async ({ dialogId, offset, count }: SyncDialogRequest) => {
      const result = await api<SyncDialogResult>(`/inbox/dialogs/${dialogId}/sync?offset=${offset}&count=${count}`, { method: 'POST' })
      if (!result.ok) throw new Error(result.error || 'Не удалось синхронизировать диалог')
      return result
    },
    onSuccess: (_result, variables) => { setSyncError(''); client.invalidateQueries({ queryKey: ['dialog', variables.dialogId] }); client.invalidateQueries({ queryKey: ['dialogs'] }) },
    onError: (error: Error) => setSyncError(error.message),
  })
  const markRead = useMutation({ mutationFn: (id: number) => api(`/inbox/dialogs/${id}/read`, { method: 'POST' }), onSuccess: (_data, id) => { client.invalidateQueries({ queryKey: ['dialogs'] }); client.invalidateQueries({ queryKey: ['accounts'] }); client.invalidateQueries({ queryKey: ['dialog', id] }) }, onError: (error: Error) => toast.error(error.message) })
  const pinDialog = useMutation({ mutationFn: ({ id, is_pinned }: { id: number; is_pinned: boolean }) => api(`/inbox/dialogs/${id}`, { method: 'PATCH', body: JSON.stringify({ is_pinned }) }), onSuccess: () => { setDialogMenu(null); client.invalidateQueries({ queryKey: ['dialogs'] }) }, onError: (error: Error) => toast.error(error.message) })
  const archiveDialog = useMutation({
    mutationFn: ({ id, restore }: { id: number; restore: boolean }) => api(`/inbox/dialogs/${id}/${restore ? 'restore' : 'archive'}`, { method: 'POST' }),
    onSuccess: (_data, variables) => {
      setDialogMenu(null)
      if (!variables.restore && selected === variables.id) setSelected(null)
      client.invalidateQueries({ queryKey: ['dialogs'] })
      client.invalidateQueries({ queryKey: ['dashboard-shell'] })
      client.invalidateQueries({ queryKey: ['accounts'] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const createQuick = useMutation({ mutationFn: (text: string) => api<QuickReply>('/quick-replies', { method: 'POST', body: JSON.stringify({ text }) }), onSuccess: () => { setQuickText(''); client.invalidateQueries({ queryKey: ['quick-replies'] }) }, onError: (error: Error) => toast.error(error.message) })
  const createFolder = useMutation({ mutationFn: ({ account_id, name }: { account_id: number; name: string }) => api<DialogFolder>('/inbox/folders', { method: 'POST', body: JSON.stringify({ account_id, name }) }), onSuccess: () => client.invalidateQueries({ queryKey: ['dialog-folders'] }), onError: (error: Error) => toast.error(error.message) })
  const renameFolder = useMutation({ mutationFn: ({ id, name }: { id: number; name: string }) => api(`/inbox/folders/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }), onSuccess: () => client.invalidateQueries({ queryKey: ['dialog-folders'] }), onError: (error: Error) => toast.error(error.message) })
  const deleteFolder = useMutation({ mutationFn: (id: number) => api(`/inbox/folders/${id}`, { method: 'DELETE' }), onSuccess: (_data, id) => { if (folderId === id) setFolderId(''); client.invalidateQueries({ queryKey: ['dialog-folders'] }); client.invalidateQueries({ queryKey: ['dialogs'] }) }, onError: (error: Error) => toast.error(error.message) })
  const setFolderMembership = useMutation({ mutationFn: ({ folder, dialog, enabled }: { folder: number; dialog: number; enabled: boolean }) => api(`/inbox/folders/${folder}/dialogs/${dialog}`, { method: enabled ? 'PUT' : 'DELETE' }), onSuccess: () => { setDialogMenu(null); client.invalidateQueries({ queryKey: ['dialogs'] }); client.invalidateQueries({ queryKey: ['dialog-folders'] }) }, onError: (error: Error) => toast.error(error.message) })
  const deleteQuick = useMutation({ mutationFn: (id: string) => api(`/quick-replies/${id}`, { method: 'DELETE' }), onSuccess: () => client.invalidateQueries({ queryKey: ['quick-replies'] }), onError: (error: Error) => toast.error(error.message) })

  const send = useMutation({
    mutationFn: async ({ dialogId = selected, text = reply, replyTo = replyTarget?.vk_message_id, forward }: { dialogId?: number | null; text?: string; replyTo?: number; forward?: Record<string, unknown> } = {}) => {
      if (dialogId == null) throw new Error('Диалог не выбран')
      const result = await api<ReplyResult>(`/inbox/dialogs/${dialogId}/reply`, { method: 'POST', body: JSON.stringify({ body: text, reply_to: replyTo, forward }) })
      if (!result.ok) throw new Error(result.error?.trim() || 'Не удалось отправить сообщение через VK')
      return { ...result, dialogId }
    },
    onSuccess: result => { setReply(''); setReplyTarget(null); setForwardTarget(null); if (result.dialogId === selected && selected != null) syncDialog.mutate({ dialogId: selected, offset: 0, count: 50 }); client.invalidateQueries({ queryKey: ['dialogs'] }) },
    onError: (error: Error) => toast.error(error.message),
  })

  const editMessage = useMutation({ mutationFn: ({ message, text }: { message: MessageItem; text: string }) => api(`/inbox/dialogs/${selected}/messages/${message.vk_message_id}`, { method: 'PATCH', body: JSON.stringify({ body: text }) }), onSuccess: () => { setMessageMenu(null); if (selected != null) syncDialog.mutate({ dialogId: selected, offset: 0, count: 50 }) }, onError: (error: Error) => toast.error(error.message) })
  const deleteMessage = useMutation({ mutationFn: (message: MessageItem) => api(`/inbox/dialogs/${selected}/messages/${message.vk_message_id}?delete_for_all=true`, { method: 'DELETE' }), onSuccess: () => { setMessageMenu(null); client.invalidateQueries({ queryKey: ['dialog', selected] }); client.invalidateQueries({ queryKey: ['dialogs'] }) }, onError: (error: Error) => toast.error(error.message) })

  const grouped = useMemo(() => {
    const map = new Map<string, Dialog[]>()
    for (const dialog of dialogs.data || []) { const list = map.get(dialog.account_name) || []; list.push(dialog); map.set(dialog.account_name, list) }
    for (const rows of map.values()) rows.sort((a, b) => Number(Boolean(b.is_pinned)) - Number(Boolean(a.is_pinned)) || String(b.pinned_at || b.last_message_at || '').localeCompare(String(a.pinned_at || a.last_message_at || '')))
    return [...map.entries()]
  }, [dialogs.data])
  const selectedDialog = useMemo(() => (dialogs.data || []).find(dialog => dialog.id === selected) || null, [dialogs.data, selected])
  const orderedFolders = useMemo(() => {
    const rows = [...(Array.isArray(folders.data) ? folders.data : [])].filter(folder => folder.name.toLowerCase().includes(folderSearch.trim().toLowerCase()))
    const rank = new Map(folderOrder.map((id, index) => [id, index]))
    return rows.sort((a, b) => (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9) || a.name.localeCompare(b.name, 'ru-RU'))
  }, [folderOrder, folderSearch, folders.data])
  const folderGroups = useMemo(() => (accounts.data || []).map(account => ({ account, folders: orderedFolders.filter(folder => folder.account_id === account.id) })).filter(group => group.folders.length), [accounts.data, orderedFolders])
  const dropFolder = (target: number) => { if (draggingFolder == null || draggingFolder === target) return setDraggingFolder(null); const ids = orderedFolders.map(folder => folder.id); const from = ids.indexOf(draggingFolder); const to = ids.indexOf(target); if (from >= 0 && to >= 0) { ids.splice(from, 1); ids.splice(to, 0, draggingFolder); setFolderOrder(ids) } setDraggingFolder(null) }
  const openFolder = (folder: DialogFolder) => { setFilter('all'); setAccountId(folder.account_id); setFolderId(folder.id) }
  const beginCreateFolder = (owner?: number) => { setFolderCreateAccountId(owner || (accountId ? Number(accountId) : '')); setFolderCreateName(''); setFolderCreateOpen(true) }

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const el = messagesRef.current; if (!el) return
    if (typeof el.scrollTo === 'function') el.scrollTo({ top: el.scrollHeight, behavior }); else el.scrollTop = el.scrollHeight
    isNearBottomRef.current = true; setShowNewMessages(false)
  }, [])

  useEffect(() => { renderedRef.current = renderedMessages }, [renderedMessages])
  useEffect(() => {
    if (selected == null) return
    setRenderedMessages([]); renderedRef.current = []; setBeforeCursor(null); setHasOlderLocal(false); setRemoteOffset(0); setHasMoreRemote(true); setSyncError(''); setShowNewMessages(false); isNearBottomRef.current = true; initialSyncRef.current = null; initializedDialogRef.current = null; setReplyTarget(null); setMessageMenu(null); setForwardTarget(null)
    syncDialog.mutate({ dialogId: selected, offset: 0, count: 50 }, { onSuccess: result => { initialSyncRef.current = result; setRemoteOffset(current => Math.max(current, result.next_offset)); setHasMoreRemote(result.has_more) } })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected])

  useEffect(() => {
    if (selected == null) return
    const dialogId = selected; let cancelled = false
    const refresh = async () => {
      try {
        const result = await api<SyncDialogResult>(`/inbox/dialogs/${dialogId}/sync?offset=0&count=50`, { method: 'POST' })
        if (!result.ok) throw new Error(result.error?.trim() || 'Не удалось обновить открытый диалог')
        if (cancelled) return; setSyncError(''); client.invalidateQueries({ queryKey: ['dialog', dialogId] }); client.invalidateQueries({ queryKey: ['dialogs'] })
      } catch (error) { if (!cancelled) setSyncError(error instanceof Error ? error.message : 'Не удалось обновить открытый диалог') }
    }
    const timer = window.setInterval(() => { void refresh() }, 5000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [client, selected])

  useEffect(() => {
    const payload = messages.data; if (selected == null || !payload) return
    const incoming = payload.messages || []; const isInitial = initializedDialogRef.current !== selected; const current = renderedRef.current
    const currentLastId = current.length ? current[current.length - 1].vk_message_id : null; const incomingLastId = incoming.length ? incoming[incoming.length - 1].vk_message_id : null
    const hasNewLastMessage = !isInitial && currentLastId != null && incomingLastId != null && incomingLastId > currentLastId
    if (isInitial) {
      initializedDialogRef.current = selected; renderedRef.current = incoming; setRenderedMessages(incoming); setBeforeCursor(payload.next_before_vk_message_id); setHasOlderLocal(payload.has_older_local)
      const syncMeta = initialSyncRef.current; setRemoteOffset(Math.max(syncMeta?.next_offset || 0, payload.local_total || 0)); if (syncMeta) setHasMoreRemote(syncMeta.has_more); requestAnimationFrame(() => scrollToBottom()); return
    }
    if (incoming.length) { const merged = new Map<number, MessageItem>(); for (const item of current) merged.set(item.vk_message_id, item); for (const item of incoming) merged.set(item.vk_message_id, item); const next = [...merged.values()].sort((left, right) => left.vk_message_id - right.vk_message_id); renderedRef.current = next; setRenderedMessages(next) }
    if (payload.next_before_vk_message_id != null && current.length === 0) { setBeforeCursor(payload.next_before_vk_message_id); setHasOlderLocal(payload.has_older_local) }
    if (hasNewLastMessage) { if (isNearBottomRef.current) requestAnimationFrame(() => scrollToBottom()); else setShowNewMessages(true) }
  }, [messages.data, scrollToBottom, selected])

  const fetchLocalOlder = useCallback(async (dialogId: number, cursor: number) => api<MessagePayload>(`/inbox/dialogs/${dialogId}?limit=200&before_vk_message_id=${cursor}`), [])
  const loadOlder = useCallback(async () => {
    const dialogId = selected; const el = messagesRef.current; const cursor = beforeCursor
    if (dialogId == null || !el || cursor == null || loadingOlderRef.current || (!hasOlderLocal && !hasMoreRemote)) return
    loadingOlderRef.current = true; const beforeHeight = el.scrollHeight
    try {
      let page = await fetchLocalOlder(dialogId, cursor); let remoteStillHasMore = hasMoreRemote
      if (!page.messages.length && !page.has_older_local && hasMoreRemote) { const synced = await syncDialog.mutateAsync({ dialogId, offset: remoteOffset, count: 200 }); setRemoteOffset(synced.next_offset); setHasMoreRemote(synced.has_more); remoteStillHasMore = synced.has_more; page = await fetchLocalOlder(dialogId, cursor) }
      if (page.messages.length) { const current = renderedRef.current; const seen = new Set(current.map(item => item.vk_message_id)); const older = page.messages.filter(item => !seen.has(item.vk_message_id)); const next = [...older, ...current]; renderedRef.current = next; setRenderedMessages(next); setBeforeCursor(page.next_before_vk_message_id); setHasOlderLocal(page.has_older_local); requestAnimationFrame(() => { const delta = el.scrollHeight - beforeHeight; if (delta > 0) el.scrollTop += delta }) }
      else if (!remoteStillHasMore) { setBeforeCursor(null); setHasOlderLocal(false) }
    } catch (error) { setSyncError(error instanceof Error ? error.message : 'Не удалось загрузить старые сообщения') } finally { loadingOlderRef.current = false }
  }, [beforeCursor, fetchLocalOlder, hasMoreRemote, hasOlderLocal, remoteOffset, selected, syncDialog])

  function handleMessageScroll() { const el = messagesRef.current; if (!el) return; const distance = el.scrollHeight - el.scrollTop - el.clientHeight; isNearBottomRef.current = distance <= 80; if (isNearBottomRef.current) setShowNewMessages(false); if (el.scrollTop <= 80 && (hasOlderLocal || hasMoreRemote)) void loadOlder() }
  function openDialog(dialog: Dialog) { setSelected(dialog.id); if (filter !== 'archive' && dialog.unread_count > 0) markRead.mutate(dialog.id) }
  function refreshCurrentDialog() { if (selected != null) syncDialog.mutate({ dialogId: selected, offset: 0, count: 50 }) }

  function insertAtCaret(text: string) {
    const area = textareaRef.current; const start = area?.selectionStart ?? reply.length; const end = area?.selectionEnd ?? start
    setReply(value => `${value.slice(0, start)}${text}${value.slice(end)}`)
    requestAnimationFrame(() => { textareaRef.current?.focus(); const position = start + text.length; textareaRef.current?.setSelectionRange(position, position) })
  }

  function handleTyping(value: string) {
    setReply(value)
    const now = Date.now()
    if (selected != null && now - lastTypingRef.current > 5000) { lastTypingRef.current = now; void api(`/inbox/dialogs/${selected}/activity`, { method: 'POST', body: JSON.stringify({ activity: 'typing' }) }).catch(() => undefined) }
  }

  useEffect(() => {
    if (activePopover === 'closed') return
    const pointer = (event: PointerEvent) => { if (!popoverRef.current?.contains(event.target as Node)) setActivePopover('closed') }
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setActivePopover('closed') }
    document.addEventListener('pointerdown', pointer); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', key) }
  }, [activePopover])

  function jumpToMessage(id: number) { document.getElementById(`message-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
  async function runMessageSearch() { if (selected == null || !messageSearch.trim()) return setSearchResults([]); try { setSearchResults(await api<MessageItem[]>(`/inbox/dialogs/${selected}/search?q=${encodeURIComponent(messageSearch.trim())}&limit=100`)) } catch (error) { toast.error(error instanceof Error ? error.message : 'Ошибка поиска') } }
  async function loadMedia(type: string) { if (selected == null) return; try { const result = await api<{ok:boolean; items:unknown[]; error?:string}>(`/inbox/dialogs/${selected}/media?media_type=${encodeURIComponent(type)}&count=100`); if (!result.ok) throw new Error(result.error || 'Не удалось загрузить вложения'); setMediaItems(result.items || []) } catch (error) { toast.error(error instanceof Error ? error.message : 'Ошибка загрузки вложений') } }

  const activePayload = messages.data; const activeDialog = activePayload?.dialog || selectedDialog; const replyAccount = activePayload?.reply_account; const canWrite = activePayload?.dialog?.can_write ?? selectedDialog?.can_write ?? true
  const forwardDialogs = (dialogs.data || []).filter(dialog => forwardTarget && activeDialog && dialog.account_id === activeDialog.account_id && dialog.id !== selected)

  return <div className="page page--inbox" onClick={() => { if (dialogMenu) setDialogMenu(null); if (messageMenu) setMessageMenu(null) }}>
    <PageHeader title="Сообщения" description="Все диалоги аккаунтов в одном рабочем окне" actions={<Button variant="secondary" disabled={!accounts.data?.length} onClick={() => accounts.data?.filter(x => x.enabled).forEach(x => syncAccounts.mutate(x.id))}><RefreshCcw size={16} />Обновить диалоги</Button>} />
    <div className="inbox-layout">
      <aside className="conversation-list">
        <div className="inbox-filters"><label className="search-box"><Search size={16} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Поиск диалогов" /></label><select value={accountId} onChange={e => setAccountId(e.target.value ? Number(e.target.value) : '')}><option value="">Все аккаунты</option>{accounts.data?.map(account => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select><div className="segmented segmented--full inbox-view-tabs"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>Все</button><button className={filter === 'unread' ? 'active' : ''} onClick={() => setFilter('unread')}>Непрочитанные</button><button className={filter === 'archive' ? 'active' : ''} onClick={() => setFilter('archive')}>Архив</button></div><div className="folder-filter folder-workspace"><div className="folder-head"><button type="button" className="folder-collapse" onClick={() => setFoldersCollapsed(value => !value)}><ChevronDown size={14} className={foldersCollapsed ? 'rotate-left' : ''} /><strong>Папки</strong></button><button type="button" onClick={() => beginCreateFolder()}>+ Создать папку</button></div>{!foldersCollapsed && <>{(folders.data?.length || 0) >= 10 && <label className="folder-search"><Search size={13} /><input value={folderSearch} onChange={event => setFolderSearch(event.target.value)} placeholder="Найти папку" /></label>}<div className="folder-scroll" data-testid="folder-scroll">{accountId ? orderedFolders.filter(folder => folder.account_id === Number(accountId)).map(folder => <div key={folder.id} className={`folder-row ${folderId === folder.id ? 'active' : ''}`} draggable onDragStart={() => setDraggingFolder(folder.id)} onDragOver={event => event.preventDefault()} onDrop={() => dropFolder(folder.id)}><button type="button" onClick={() => { setFilter('all'); setFolderId(folderId === folder.id ? '' : folder.id) }}><span>{folder.name}</span><b>{folder.dialogs_count}</b></button><button type="button" aria-label={`Переименовать папку ${folder.name}`} onClick={() => { const name = prompt('Новое название папки', folder.name)?.trim(); if (name) renameFolder.mutate({ id: folder.id, name }) }}>✎</button><button type="button" aria-label={`Удалить папку ${folder.name}`} onClick={() => confirm(`Удалить папку «${folder.name}»? Диалоги останутся.`) && deleteFolder.mutate(folder.id)}>×</button></div>) : folderGroups.map(({ account, folders: rows }) => <section className="folder-account-group" key={account.id}><header>{account.display_name}</header>{rows.map(folder => <div key={folder.id} className="folder-row" draggable onDragStart={() => setDraggingFolder(folder.id)} onDragOver={event => event.preventDefault()} onDrop={() => dropFolder(folder.id)}><button type="button" onClick={() => openFolder(folder)}><span>{folder.name}</span><b>{folder.dialogs_count}</b></button><button type="button" aria-label={`Переименовать папку ${folder.name}`} onClick={() => { const name = prompt('Новое название папки', folder.name)?.trim(); if (name) renameFolder.mutate({ id: folder.id, name }) }}>✎</button><button type="button" aria-label={`Удалить папку ${folder.name}`} onClick={() => confirm(`Удалить папку «${folder.name}»? Диалоги останутся.`) && deleteFolder.mutate(folder.id)}>×</button></div>)}</section>)}</div>{folderCreateOpen && <div className="folder-create-panel"><select aria-label="Аккаунт папки" value={folderCreateAccountId} onChange={event => setFolderCreateAccountId(event.target.value ? Number(event.target.value) : '')}><option value="">Выберите аккаунт</option>{accounts.data?.map(account => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select><input aria-label="Название папки" value={folderCreateName} onChange={event => setFolderCreateName(event.target.value)} placeholder="Название папки" /><div><button type="button" disabled={!folderCreateAccountId || !folderCreateName.trim()} onClick={() => { if (folderCreateAccountId && folderCreateName.trim()) createFolder.mutate({ account_id: Number(folderCreateAccountId), name: folderCreateName.trim() }, { onSuccess: () => { setFolderCreateOpen(false); setFolderCreateName('') } }) }}>Создать</button><button type="button" onClick={() => setFolderCreateOpen(false)}>Отмена</button></div></div>}</>}</div></div>
        <div className="dialog-scroll" data-testid="dialog-scroll">
          {grouped.length ? grouped.map(([accountName, rows]) => { const closed = collapsed.has(accountName); return <section className={`dialog-group ${closed ? 'dialog-group--collapsed' : ''}`} key={accountName}><header><button onClick={() => setCollapsed(previous => { const next = new Set(previous); next.has(accountName) ? next.delete(accountName) : next.add(accountName); return next })}><ChevronDown size={14} /><UserRound size={15} /><strong>{accountName}</strong>{filter !== 'archive' && <span>{rows.filter(row => row.unread_count > 0).length}</span>}</button></header>{!closed && rows.map(dialog => <button key={dialog.id} className={selected === dialog.id ? 'active' : ''} onClick={() => openDialog(dialog)} onContextMenu={event => { event.preventDefault(); event.stopPropagation(); setDialogMenu({ value: dialog, x: event.clientX, y: event.clientY }) }}>{dialog.avatar_url ? <img src={dialog.avatar_url} alt="" /> : <div className="dialog-avatar">{dialog.title.slice(0, 1)}</div>}<div className="dialog-card-copy"><div className="dialog-title-row"><strong>{dialog.is_pinned && <Pin size={11} className="pin-inline" />}{dialog.title}</strong><time>{dialog.last_message_at ? formatLocalDateTime(dialog.last_message_at) : ''}</time></div><small className="dialog-preview">{lastMessagePreview(dialog)}</small></div>{filter !== 'archive' && dialog.unread_count > 0 && <b className="dialog-unread">{dialog.unread_count}</b>}</button>)}</section> }) : <EmptyState icon={<Inbox />} title={filter === 'archive' ? 'Архив пуст' : 'Диалогов пока нет'} text={filter === 'archive' ? 'Архивированные диалоги появятся здесь и останутся до ручного возврата.' : 'Синхронизация выполняется автоматически; при необходимости нажмите «Обновить диалоги».'} />}
        </div>
      </aside>

      <section className="chat-panel">
        {selected == null ? <EmptyState icon={<MessageCircle />} title="Выберите диалог" text="Слева находятся переписки, сгруппированные по аккаунтам." /> : <>
          <header className="chat-head"><div className="chat-peer"><h2>{activeDialog?.title || 'Диалог'}</h2><div className="reply-identity"><span>Вы отвечаете от:</span><strong>{replyAccount?.note || replyAccount?.name || activeDialog?.account_name || 'Загрузка…'}</strong>{replyAccount?.avatar_url ? <img alt={replyAccount.name} src={replyAccount.avatar_url} /> : <div className="reply-avatar-fallback">{(replyAccount?.name || activeDialog?.account_name || '?').slice(0, 1)}</div>}</div></div><div className="chat-head-actions"><button type="button" className="icon-button" aria-label="Поиск в переписке" onClick={() => setMessageSearchOpen(value => !value)}><Search size={16} /></button><button type="button" className="icon-button" aria-label="Медиа и вложения" onClick={() => setMediaOpen(value => !value)}><Paperclip size={16} /></button><Button variant="ghost" aria-label="Обновить диалог" onClick={refreshCurrentDialog} loading={syncDialog.isPending}><RefreshCcw size={16} /></Button></div></header>
          {messageSearchOpen && <div className="chat-tool-panel"><label className="search-box"><Search size={15} /><input value={messageSearch} onChange={e => setMessageSearch(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') void runMessageSearch() }} placeholder="Поиск по сообщениям" /></label><button onClick={() => void runMessageSearch()}>Найти</button>{searchResults.map(item => <button key={item.vk_message_id} className="search-result" onClick={() => jumpToMessage(item.vk_message_id)}>{item.body || 'Вложение'} · {formatLocalDate(item.sent_at)}</button>)}</div>}
          {mediaOpen && <div className="chat-tool-panel media-panel"><div>{[['photo','Фото'],['video','Видео'],['doc','Файлы'],['audio_message','Голосовые'],['link','Ссылки']].map(([type,label]) => <button key={type} onClick={() => void loadMedia(type)}>{label}</button>)}</div><pre>{mediaItems.length ? JSON.stringify(mediaItems, null, 2) : 'Выберите тип вложений'}</pre></div>}
          <div className="messages-stage"><div className="messages-scroll" data-testid="messages-scroll" ref={messagesRef} onScroll={handleMessageScroll}>{(syncDialog.isPending || messages.isPending) && <div className="chat-sync-state">Синхронизирую историю…</div>}{syncError && <div className="chat-sync-error"><span>{syncError}</span><button onClick={refreshCurrentDialog}>Повторить</button></div>}{messages.isError && !renderedMessages.length && <div className="chat-sync-error"><span>{messages.error instanceof Error ? messages.error.message : 'Не удалось загрузить историю'}</span><button onClick={() => messages.refetch()}>Повторить</button></div>}{renderedMessages.map(message => <MessageBubble key={message.vk_message_id} message={message} onReplyJump={jumpToMessage} onContextMenu={(event, value) => { event.preventDefault(); event.stopPropagation(); setMessageMenu({ value, x: event.clientX, y: event.clientY }) }} />)}{!messages.isPending && !renderedMessages.length && !messages.isError && <div className="chat-empty">В этом диалоге пока нет сообщений</div>}</div>{showNewMessages && <button className="new-messages-button" aria-label="Новые сообщения" onClick={() => scrollToBottom('smooth')}>↓ Новые сообщения</button>}</div>
          {canWrite ? <form className="composer" onSubmit={e => { e.preventDefault(); if (reply.trim()) send.mutate({}) }}>
            <div className="reply-account">От: <strong>{replyAccount?.note || replyAccount?.name || activeDialog?.account_name || 'аккаунт'}</strong></div>
            {replyTarget && <div className="composer-reply"><span>Ответ на: {replyTarget.body || 'вложение'}</span><button type="button" aria-label="Отменить ответ" onClick={() => setReplyTarget(null)}><X size={13} /></button></div>}
            <textarea ref={textareaRef} aria-label="Ответ" value={reply} onChange={e => handleTyping(e.target.value)} placeholder="Напишите ответ…" onKeyDown={e => { if (e.key === 'Escape') { setReplyTarget(null); setActivePopover('closed') } else if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (reply.trim()) send.mutate({}) } }} />
            <div className="composer-control-stack" data-testid="composer-controls" ref={popoverRef}>
              <button type="button" className="composer-icon-action" aria-label="Смайлики" onClick={() => setActivePopover(value => value === 'emoji' ? 'closed' : 'emoji')}><Smile size={17} /></button>
              <button type="button" className="composer-icon-action" aria-label="Быстрые ответы" onClick={() => setActivePopover(value => value === 'quick' ? 'closed' : 'quick')}><Zap size={17} /></button>
              <Button type="submit" disabled={!reply.trim()} loading={send.isPending}><Send size={17} />Отправить</Button>
              {activePopover === 'emoji' && <div className="composer-popover composer-popover--emoji"><EmojiPicker onInsert={emoji => insertAtCaret(emoji)} /></div>}
              {activePopover === 'quick' && <div className="quick-replies-popover composer-popover"><header><strong>Быстрые ответы</strong><button type="button" aria-label="Закрыть быстрые ответы" onClick={() => setActivePopover('closed')}><X size={14} /></button></header>{quickReplies.isLoading ? <span>Загрузка…</span> : quickReplies.data?.length ? <div className="quick-reply-list">{quickReplies.data.map(item => <div key={item.id}><button type="button" className="quick-reply-value" onClick={() => insertAtCaret(item.text)}>{item.text}</button><button type="button" aria-label={`Изменить ${item.text}`} onClick={() => { const text = prompt('Новый текст шаблона', item.text)?.trim(); if (text) void api(`/quick-replies/${item.id}`, { method: 'PATCH', body: JSON.stringify({ text }) }).then(() => client.invalidateQueries({ queryKey: ['quick-replies'] })).catch(error => toast.error(error.message)) }}>✎</button><button type="button" aria-label={`Удалить ${item.text}`} onClick={() => { if (confirm('Удалить этот шаблон?')) deleteQuick.mutate(item.id) }}>×</button></div>)}</div> : <div className="quick-empty">Шаблонов ещё нет</div>}<div className="quick-create"><textarea value={quickText} onChange={e => setQuickText(e.target.value)} placeholder="Текст нового шаблона" /><Button type="button" disabled={!quickText.trim()} onClick={() => createQuick.mutate(quickText)}><Plus size={14} />Создать шаблон</Button></div></div>}
            </div>
          </form> : <div className="composer-unavailable"><MessageCircle size={18} /><div><strong>Отправка сообщений в этот диалог недоступна</strong>{activePayload?.dialog.write_disabled_reason && <span>VK не разрешает отправку для этого диалога.</span>}</div></div>}
        </>}
      </section>
    </div>

    {dialogMenu && <div className="context-menu" style={{ left: dialogMenu.x, top: dialogMenu.y }} onClick={event => event.stopPropagation()}>{filter === 'archive' || dialogMenu.value.is_archived ? <button onClick={() => archiveDialog.mutate({ id: dialogMenu.value.id, restore: true })}>Вернуть из архива</button> : <><button onClick={() => archiveDialog.mutate({ id: dialogMenu.value.id, restore: false })}>В архив</button><button onClick={() => pinDialog.mutate({ id: dialogMenu.value.id, is_pinned: !dialogMenu.value.is_pinned })}>{dialogMenu.value.is_pinned ? 'Открепить' : 'Закрепить'}</button><div className="context-submenu-label">Добавить в папку ›</div>{(Array.isArray(folders.data) ? folders.data : []).filter(folder => folder.account_id === dialogMenu.value.account_id).map(folder => { const active = Boolean(dialogMenu.value.folder_ids?.includes(folder.id)); return <button key={folder.id} onClick={() => setFolderMembership.mutate({ folder: folder.id, dialog: dialogMenu.value.id, enabled: !active })}>{active ? '✓ ' : ''}{folder.name}</button> })}<button onClick={() => { beginCreateFolder(dialogMenu.value.account_id); setDialogMenu(null) }}>+ Новая папка</button></>}</div>}
    {messageMenu && <div className="context-menu" style={{ left: messageMenu.x, top: messageMenu.y }} onClick={event => event.stopPropagation()}><button onClick={() => { setReplyTarget(messageMenu.value); setMessageMenu(null); textareaRef.current?.focus() }}>Ответить</button><button onClick={() => { setForwardTarget(messageMenu.value); setMessageMenu(null) }}>Переслать</button>{messageMenu.value.outgoing && <button onClick={() => { const text = prompt('Изменить сообщение', messageMenu.value.body)?.trim(); if (text != null) editMessage.mutate({ message: messageMenu.value, text }) }}>Редактировать</button>}<button onClick={() => navigator.clipboard?.writeText(messageMenu.value.body || '')}>Скопировать текст</button><button onClick={() => navigator.clipboard?.writeText(String(messageMenu.value.vk_message_id))}>Скопировать ID</button><button className="danger-text" onClick={() => { if (confirm('Удалить сообщение у всех, если VK это разрешит?')) deleteMessage.mutate(messageMenu.value) }}>Удалить</button></div>}
    {forwardTarget && <div className="modal-backdrop" onClick={() => setForwardTarget(null)}><div className="forward-picker" onClick={event => event.stopPropagation()}><header><strong>Переслать сообщение</strong><button onClick={() => setForwardTarget(null)}><X size={15} /></button></header><p>Настоящая пересылка доступна в диалоги того же VK-аккаунта.</p>{forwardDialogs.length ? forwardDialogs.map(dialog => <button key={dialog.id} onClick={() => send.mutate({ dialogId: dialog.id, text: '', replyTo: undefined, forward: { peer_id: activeDialog?.peer_id, message_ids: [forwardTarget.vk_message_id] } })}>{dialog.avatar_url ? <img src={dialog.avatar_url} alt="" /> : <span>{dialog.title.slice(0,1)}</span>}<b>{dialog.title}</b></button>) : <div className="soft-empty">Других диалогов этого аккаунта нет</div>}</div></div>}
  </div>
}
