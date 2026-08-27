import type { MessageAttachment, MessageItem, NestedMessage } from '../types'
import { formatLocalDateTime } from '../utils/time'

function firstUrl(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null
  const object = value as Record<string, unknown>
  for (const key of ['url', 'link_mp3', 'link_ogg', 'player']) if (typeof object[key] === 'string') return object[key] as string
  const sizes = object.sizes
  if (Array.isArray(sizes)) {
    const candidates = sizes.filter(item => item && typeof item === 'object' && typeof (item as Record<string, unknown>).url === 'string') as Record<string, unknown>[]
    const best = candidates.at(-1)
    if (best) return best.url as string
  }
  const images = object.images
  if (Array.isArray(images)) {
    const candidates = images.filter(item => item && typeof item === 'object' && typeof (item as Record<string, unknown>).url === 'string') as Record<string, unknown>[]
    const best = candidates.at(-1)
    if (best) return best.url as string
  }
  return null
}

function Attachment({ attachment }: { attachment: MessageAttachment }) {
  const payload = attachment[attachment.type] as Record<string, unknown> | undefined
  if (attachment.type === 'sticker') {
    const src = firstUrl(payload)
    return src ? <img className="vk-sticker" src={src} alt="Стикер" /> : <div className="attachment-card">Стикер</div>
  }
  if (attachment.type === 'audio_message') {
    const src = firstUrl(payload)
    const duration = payload && typeof payload.duration === 'number' ? payload.duration : null
    return <div className="voice-card"><strong>🎙 Голосовое{duration != null ? ` · ${duration} сек` : ''}</strong>{src ? <audio controls preload="none" src={src} /> : <span>Аудиофайл недоступен</span>}</div>
  }
  if (attachment.type === 'photo') {
    const src = firstUrl(payload)
    return src ? <a href={src} target="_blank" rel="noreferrer"><img className="message-photo" src={src} alt="Фото" /></a> : <div className="attachment-card">Фото</div>
  }
  const url = firstUrl(payload)
  const labels: Record<string, string> = { video: 'Видео', clip: 'Клип', doc: 'Файл', audio: 'Аудио', link: 'Ссылка', wall: 'Запись', graffiti: 'Граффити', market: 'Товар' }
  const label = labels[attachment.type] || `Вложение: ${attachment.type}`
  return url ? <a className="attachment-card" href={url} target="_blank" rel="noreferrer">{label}</a> : <div className="attachment-card">{label}</div>
}

function Nested({ value, title }: { value: NestedMessage; title: string }) {
  return <div className="nested-message"><b>{title}</b><span>{value.text || (value.attachments?.length ? 'Вложение' : 'Сообщение')}</span>{value.attachments?.slice(0, 2).map((item, index) => <Attachment key={index} attachment={item} />)}</div>
}

export default function MessageBubble({ message, onContextMenu, onReplyJump }: { message: MessageItem; onContextMenu: (event: React.MouseEvent, message: MessageItem) => void; onReplyJump?: (id: number) => void }) {
  if (message.deleted) return <div id={`message-${message.vk_message_id}`} className={`bubble bubble--deleted ${message.outgoing ? 'bubble--out' : ''}`} onContextMenu={event => onContextMenu(event, message)}><p>Сообщение удалено</p></div>
  const replyId = message.reply_message?.id
  return <div id={`message-${message.vk_message_id}`} className={`bubble ${message.outgoing ? 'bubble--out' : ''}`} onContextMenu={event => onContextMenu(event, message)}>
    {message.reply_message?.id && <button type="button" className="reply-preview" onClick={() => replyId && onReplyJump?.(replyId)}><Nested value={message.reply_message} title="Ответ на сообщение" /></button>}
    {message.forwarded_messages?.map((value, index) => <Nested key={index} value={value} title="Пересланное сообщение" />)}
    {message.body && <p>{message.body}</p>}
    {message.attachments?.map((attachment, index) => <Attachment key={`${attachment.type}-${index}`} attachment={attachment} />)}
    {!message.body && !message.attachments?.length && !message.forwarded_messages?.length && <p>Вложение</p>}
    <time>{formatLocalDateTime(message.sent_at)}{message.updated_at ? ' · изменено' : ''}{message.outgoing && message.is_read ? ' · прочитано' : ''}</time>
  </div>
}
