import assert from 'node:assert/strict'
import test from 'node:test'
import { Children, isValidElement } from 'react'
import ButtonListEditor from '../src/features/funnels/components/ButtonListEditor'

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
