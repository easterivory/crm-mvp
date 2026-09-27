import assert from 'node:assert/strict'
import test from 'node:test'
import { Children, isValidElement } from 'react'
import ButtonListEditor from '../src/features/funnels/components/ButtonListEditor'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import MessageSequenceEditor from '../src/features/funnels/components/MessageSequenceEditor'
import MessageBlockSettings from '../src/features/funnels/components/MessageBlockSettings'
import { normalizeMessages } from '../src/features/funnels/funnelConfig'
import type { FunnelStep } from '../src/features/funnels/types'

const messageStep: FunnelStep = {
  id: 'source', key: 'source', title: 'Message', step_type: 'message', block_type: 'generic_message',
  position_x: 10, position_y: 20, validation_json: null, ui_schema_json: null,
  config_json: { auto_advance_enabled: true, timeout_target_step_id: 'timeout', messages: [
    { id: 'first', type: 'text', text: 'First message', buttons: [{ id: 'route', label: 'Next', type: 'branch', value: 'next', target_step_id: 'target' }] },
    { id: 'second', type: 'text', text: 'Second message', buttons: [] },
  ] },
}

test('expanded editor selects requested message and renders preview without changing data', () => {
  const messages = normalizeMessages(messageStep.config_json)
  const before = JSON.stringify(messages)
  const html = renderToStaticMarkup(createElement(MessageSequenceEditor, {
    messages, currentStepId: 'source', projectId: 'project', steps: [messageStep],
    expanded: true, initialMessageId: 'second', onChange: () => { throw new Error('Render must not mutate') },
  }))
  assert.ok(html.includes('TELEGRAM'))
  assert.ok(html.includes('Second message'))
  assert.ok(html.includes('Сообщения блока'))
  assert.equal(JSON.stringify(messages), before)
})

test('content edits preserve timer and button routes and synchronize legacy message fields', () => {
  let result: Record<string, unknown> | undefined
  const tree = MessageBlockSettings({ step: messageStep, projectId: 'project', steps: [messageStep], section: 'content', onConfigChange: (config) => { result = config } })
  const editor = Children.toArray(tree.props.children).find((item) => isValidElement(item) && item.type === MessageSequenceEditor)
  assert.ok(isValidElement(editor))
  const props = editor.props as { onChange: (messages: ReturnType<typeof normalizeMessages>) => void }
  const messages = normalizeMessages(messageStep.config_json)
  messages[0].text = 'Edited'
  props.onChange(messages)
  assert.equal(result?.text, 'Edited')
  assert.equal(result?.timeout_target_step_id, 'timeout')
  assert.equal(result?.auto_advance_enabled, true)
  assert.equal(normalizeMessages(result!)[0].buttons[0].target_step_id, 'target')
})

function selects(tree: any): any[] {
  if (!isValidElement(tree)) return []
  return [ ...(tree.type === 'select' ? [tree] : []),
    ...Children.toArray((tree.props as any).children).flatMap(selects) ]
}

test('keyboard mode and buttons are saved in one update with routes intact', () => {
  const changes: any[] = []
  const buttons = [{ id: 'one', label: 'Next', value: 'next', type: 'branch' as const, target_step_id: 'target' }]
  const tree = ButtonListEditor({ buttons, steps: [], currentStepId: 'source', allowModeChange: true,
    onChange: (...args) => changes.push(args) })
  selects(tree)[0].props.onChange({ target: { value: 'reply' } })
  assert.equal(changes.length, 1)
  assert.equal(changes[0][1], 'reply')
  assert.deepEqual(changes[0][0], buttons)
})

test('switching to URL changes placement and contact mode atomically', () => {
  const changes: any[] = []
  const buttons = [
    { id: 'one', label: 'Next', value: 'next', type: 'branch' as const },
    { id: 'contact', label: 'Phone', value: 'contact', type: 'contact' as const, contact_mode: 'native' as const, target_step_id: 'target' },
  ]
  const tree = ButtonListEditor({ buttons, steps: [], currentStepId: 'source', allowModeChange: true,
    buttonMode: 'reply', onChange: (...args) => changes.push(args) })
  selects(tree)[1].props.onChange({ target: { value: 'url' } })
  assert.equal(changes.length, 1)
  assert.equal(changes[0][1], 'inline')
  assert.equal(changes[0][0][1].contact_mode, 'mini_app')
  assert.equal(changes[0][0][1].target_step_id, 'target')
})

test('adding a contact to a reply keyboard chooses native contact', () => {
  const changes: any[] = []
  const tree = ButtonListEditor({ buttons: [{ id: 'one', label: 'Phone', value: 'phone', type: 'branch' }],
    steps: [], currentStepId: 'source', allowModeChange: true, buttonMode: 'reply',
    onChange: (...args) => changes.push(args) })
  selects(tree)[1].props.onChange({ target: { value: 'contact' } })
  assert.equal(changes.length, 1)
  assert.equal(changes[0][0][0].contact_mode, 'native')
  assert.equal(changes[0][1], 'reply')
})
