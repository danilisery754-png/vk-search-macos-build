import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type PropsWithChildren } from 'react'
import { ApiError } from '../api/client'
import { useSessionUiStore } from './SessionUiStore'

const INBOX_SNAPSHOT_KEY = 'inbox'
const DIALOG_LIST_SCROLL_KEY = 'inbox-scroll:dialog-list'
const MESSAGE_SCROLL_PREFIX = 'inbox-scroll:messages:'

interface InboxSelectionSnapshot {
  selectedDialogId?: number | null
  [key: string]: unknown
}

function safeScrollTop(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

function hasStoredScroll(value: unknown): boolean {
  return Number.isFinite(Number(value)) && Number(value) >= 0
}

export default function InboxScrollMemory({ children }: PropsWithChildren) {
  const uiStore = useSessionUiStore()
  const queryClient = useQueryClient()
  const rootRef = useRef<HTMLDivElement>(null)
  const restoredDialogListRef = useRef<HTMLElement | null>(null)
  const restoredMessageDialogRef = useRef<number | null>(null)
  const [contentGeneration, setContentGeneration] = useState(0)

  useEffect(() => queryClient.getQueryCache().subscribe(event => {
    if (!('query' in event)) return
    const query = event.query
    const [scope, rawDialogId] = query.queryKey
    if (scope !== 'dialog' || query.state.status !== 'error') return
    const error = query.state.error
    if (!(error instanceof ApiError) || error.status !== 404) return
    const dialogId = Number(rawDialogId)
    if (!Number.isInteger(dialogId)) return
    const snapshot = uiStore.read<InboxSelectionSnapshot>(INBOX_SNAPSHOT_KEY)
    if (!snapshot || snapshot.selectedDialogId !== dialogId) return
    uiStore.write<InboxSelectionSnapshot>(INBOX_SNAPSHOT_KEY, { ...snapshot, selectedDialogId: null })
    setContentGeneration(value => value + 1)
  }), [queryClient, uiStore])

  useEffect(() => {
    const root = rootRef.current
    if (!root) return

    let dialogElement: HTMLElement | null = null
    let messageElement: HTMLElement | null = null
    let scheduledAttach: number | null = null
    let restoreTimerOne: number | null = null
    let restoreTimerTwo: number | null = null
    let observedDialogId: number | null = null

    const cancelMessageRestore = () => {
      if (restoreTimerOne != null) window.clearTimeout(restoreTimerOne)
      if (restoreTimerTwo != null) window.clearTimeout(restoreTimerTwo)
      restoreTimerOne = null
      restoreTimerTwo = null
    }

    const selectedDialogId = () => {
      const snapshot = uiStore.read<InboxSelectionSnapshot>(INBOX_SNAPSHOT_KEY)
      const value = snapshot?.selectedDialogId
      return typeof value === 'number' && Number.isInteger(value) ? value : null
    }

    const onDialogScroll = (event: Event) => {
      const element = event.currentTarget as HTMLElement
      uiStore.write(DIALOG_LIST_SCROLL_KEY, element.scrollTop)
    }

    const onMessageScroll = (event: Event) => {
      const dialogId = selectedDialogId()
      if (dialogId == null) return
      cancelMessageRestore()
      restoredMessageDialogRef.current = dialogId
      const element = event.currentTarget as HTMLElement
      uiStore.write(`${MESSAGE_SCROLL_PREFIX}${dialogId}`, element.scrollTop)
    }

    const scheduleMessageRestore = (dialogId: number) => {
      if (!messageElement || restoredMessageDialogRef.current === dialogId) return
      if (root.querySelector('.chat-sync-state')) return

      const stored = uiStore.read<number>(`${MESSAGE_SCROLL_PREFIX}${dialogId}`)
      if (!hasStoredScroll(stored)) {
        restoredMessageDialogRef.current = dialogId
        return
      }

      cancelMessageRestore()
      restoreTimerOne = window.setTimeout(() => {
        restoreTimerOne = null
        restoreTimerTwo = window.setTimeout(() => {
          restoreTimerTwo = null
          if (selectedDialogId() !== dialogId) return
          const current = root.querySelector<HTMLElement>('.messages-scroll')
          if (!current) return
          current.scrollTop = safeScrollTop(stored)
          restoredMessageDialogRef.current = dialogId
        }, 0)
      }, 0)
    }

    const attach = () => {
      scheduledAttach = null
      const nextDialogElement = root.querySelector<HTMLElement>('.dialog-scroll')
      if (nextDialogElement !== dialogElement) {
        dialogElement?.removeEventListener('scroll', onDialogScroll)
        dialogElement = nextDialogElement
        if (dialogElement) {
          dialogElement.addEventListener('scroll', onDialogScroll, { passive: true })
          if (restoredDialogListRef.current !== dialogElement) {
            dialogElement.scrollTop = safeScrollTop(uiStore.read<number>(DIALOG_LIST_SCROLL_KEY))
            restoredDialogListRef.current = dialogElement
          }
        }
      }

      const nextMessageElement = root.querySelector<HTMLElement>('.messages-scroll')
      if (nextMessageElement !== messageElement) {
        messageElement?.removeEventListener('scroll', onMessageScroll)
        messageElement = nextMessageElement
        if (messageElement) messageElement.addEventListener('scroll', onMessageScroll, { passive: true })
      }

      const dialogId = selectedDialogId()
      if (dialogId !== observedDialogId) {
        observedDialogId = dialogId
        cancelMessageRestore()
        restoredMessageDialogRef.current = null
      }
      if (dialogId == null) {
        restoredMessageDialogRef.current = null
        return
      }
      scheduleMessageRestore(dialogId)
    }

    const scheduleAttach = () => {
      if (scheduledAttach != null) window.clearTimeout(scheduledAttach)
      scheduledAttach = window.setTimeout(attach, 0)
    }

    attach()
    const observer = new MutationObserver(scheduleAttach)
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'data-selected'] })

    return () => {
      observer.disconnect()
      if (scheduledAttach != null) window.clearTimeout(scheduledAttach)
      cancelMessageRestore()
      dialogElement?.removeEventListener('scroll', onDialogScroll)
      messageElement?.removeEventListener('scroll', onMessageScroll)
      restoredDialogListRef.current = null
      restoredMessageDialogRef.current = null
    }
  }, [uiStore])

  return <div ref={rootRef} style={{ display: 'contents' }}><div key={contentGeneration} style={{ display: 'contents' }}>{children}</div></div>
}