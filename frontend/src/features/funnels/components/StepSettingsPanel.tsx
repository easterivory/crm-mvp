import { ChevronDown, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import api from '../../../api/client'
import { getBlockLabel, mvpBlockTypes, universalBlocks } from '../blockCatalog'
import {
  actionTypes,
  boolValue,
  collectConfiguredOutputs,
  configId,
  leadFields,
  normalizeActions,
  numberValue,
  textValue,
} from '../funnelConfig'
import type { FunnelStep } from '../types'
import AbTestBlockSettings from './AbTestBlockSettings'
import ConditionBlockSettings from './ConditionBlockSettings'
import InputBlockSettings from './InputBlockSettings'
import MessageBlockSettings from './MessageBlockSettings'
import { TargetSelect } from './ButtonListEditor'
import UnsupportedBlockCard from './UnsupportedBlockCard'

type StepSettingsPanelProps = {
  step: FunnelStep | null
  projectId: string
  steps: FunnelStep[]
  onUpdate: (stepId: string, patch: Partial<FunnelStep>) => void
  onDelete: (stepId: string) => void
}

type BuilderRef = {
  id: string
  name?: string
  code?: string
  title?: string
  ref_code?: string
}

export default function StepSettingsPanel({
  step,
  projectId,
  steps,
  onUpdate,
  onDelete,
}: StepSettingsPanelProps) {
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false)
  const [tags, setTags] = useState<BuilderRef[]>([])
  const [statuses, setStatuses] = useState<BuilderRef[]>([])
  const [trackingLinks, setTrackingLinks] = useState<BuilderRef[]>([])
  const [partnerIntegrations, setPartnerIntegrations] = useState<BuilderRef[]>([])
  const [newTagName, setNewTagName] = useState('')

  useEffect(() => {
    let cancelled = false
    const loadRefs = async () => {
      try {
        const [tagsResponse, statusesResponse, linksResponse, partnersResponse] = await Promise.all([
          api.get('/tags', { params: { project_id: projectId, limit: 100, offset: 0 } }),
          api.get('/leads/statuses'),
          api.get('/tracking/links', { params: { project_id: projectId, limit: 100, offset: 0 } }),
          api.get('/partners', { params: { project_id: projectId } }),
        ])
        if (cancelled) return
        setTags(tagsResponse.data.items ?? [])
        setStatuses(statusesResponse.data ?? [])
        setTrackingLinks(linksResponse.data.items ?? [])
        setPartnerIntegrations(partnersResponse.data.items ?? partnersResponse.data ?? [])
      } catch {
        if (!cancelled) {
          setTags([])
          setStatuses([])
          setTrackingLinks([])
          setPartnerIntegrations([])
        }
      }
    }
    void loadRefs()
    return () => {
      cancelled = true
    }
  }, [projectId])

  const createTag = async () => {
    const name = newTagName.trim()
    if (!name) return
    const { data } = await api.post('/tags', { name }, { params: { project_id: projectId } })
    setTags((current) => [...current, data])
    setNewTagName('')
  }

  if (!step) {
    return (
      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <h3 className="text-sm font-semibold text-white">Выберите блок на холсте</h3>
        <p className="mt-2 text-sm leading-5 text-gray-500">
          Inspector покажет настройки, выходы и дополнительные параметры выбранного блока.
        </p>
      </section>
    )
  }

  const isSupported = mvpBlockTypes.has(step.block_type)
  const isUniversalBlock = universalBlocks.some((item) => item.blockType === step.block_type)
  const actions = normalizeActions(step.config_json.actions)
  const outputs = collectConfiguredOutputs(step)

  const patchConfig = (patch: Record<string, unknown>) => {
    onUpdate(step.id, { config_json: { ...step.config_json, ...patch } })
  }
  const replaceConfig = (config: Record<string, unknown>) => {
    onUpdate(step.id, { config_json: config })
  }

  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-white">{step.title}</h3>
            <p className="truncate text-xs text-gray-500">{getBlockLabel(step.block_type)}</p>
          </div>
          <button
            type="button"
            onClick={() => onDelete(step.id)}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
            title="Удалить блок"
          >
            <Trash2 size={14} />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
              Название
            </span>
            <input
              value={step.title}
              onChange={(event) => onUpdate(step.id, { title: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
              Тип блока
            </span>
            <select
              value={isUniversalBlock ? step.block_type : '__legacy__'}
              onChange={(event) => {
                if (event.target.value === '__legacy__') {
                  return
                }
                const item = universalBlocks.find((candidate) => candidate.blockType === event.target.value)
                if (!item) {
                  return
                }
                onUpdate(step.id, {
                  title: item.defaultTitle,
                  step_type: item.stepType,
                  block_type: item.blockType,
                  config_json: item.defaultConfig ?? {},
                })
              }}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
            >
              {!isUniversalBlock ? (
                <option value="__legacy__">{getBlockLabel(step.block_type)} · legacy</option>
              ) : null}
              {universalBlocks.map((item) => (
                <option key={item.blockType} value={item.blockType}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {!isSupported ? (
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
          <UnsupportedBlockCard blockType={step.block_type} />
        </div>
      ) : null}

      {isSupported ? (
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
          {step.block_type === 'generic_trigger' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Триггер
              </span>
              <select
                value={textValue(step.config_json, 'trigger_type') || 'new_chat'}
                onChange={(event) => patchConfig({ trigger_type: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                <option value="new_chat">Новый чат</option>
                <option value="start_command">/start</option>
                <option value="start_with_ref_code">/start с ref-кодом</option>
                <option value="manual_operator_start">Ручной запуск</option>
              </select>
            </label>
          ) : null}

          {step.block_type === 'generic_message' ? (
            <MessageBlockSettings
              step={step}
              projectId={projectId}
              steps={steps}
              onConfigChange={replaceConfig}
            />
          ) : null}

          {step.step_type === 'message' && step.block_type !== 'generic_message' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Текст сообщения
              </span>
              <textarea
                rows={4}
                value={textValue(step.config_json, 'text') || textValue(step.config_json, 'message_text')}
                onChange={(event) => patchConfig({ text: event.target.value })}
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          ) : null}

          {step.block_type === 'generic_input' ? (
            <InputBlockSettings step={step} steps={steps} onConfigChange={replaceConfig} />
          ) : null}

          {step.step_type === 'input' && step.block_type !== 'generic_input' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Текст вопроса
              </span>
              <textarea
                rows={3}
                value={textValue(step.config_json, 'question_text') || textValue(step.config_json, 'text')}
                onChange={(event) => patchConfig({ question_text: event.target.value })}
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          ) : null}

          {step.block_type === 'generic_condition' ? (
            <ConditionBlockSettings
              step={step}
              steps={steps}
              tags={tags}
              statuses={statuses}
              trackingLinks={trackingLinks}
              onConfigChange={replaceConfig}
            />
          ) : null}

          {step.block_type === 'generic_hold_router' ? (
            <ConditionBlockSettings
              step={step}
              steps={steps}
              tags={tags}
              statuses={statuses}
              trackingLinks={trackingLinks}
              onConfigChange={replaceConfig}
            />
          ) : null}

          {step.block_type === 'generic_ab_test' ? (
            <AbTestBlockSettings step={step} steps={steps} onConfigChange={replaceConfig} />
          ) : null}

          {step.block_type === 'generic_crm_action' ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  Действия
                </span>
                <button
                  type="button"
                  onClick={() =>
                    patchConfig({
                      actions: [
                        ...actions,
                        { id: configId('action'), type: 'set_lead_status', status: 'in_progress' },
                      ],
                    })
                  }
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
                >
                  Добавить
                </button>
              </div>
              {actions.map((action, index) => (
                <div key={action.id} className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-2">
                  <select
                    value={action.type}
                    onChange={(event) =>
                      patchConfig({
                        actions: actions.map((item, idx) =>
                          idx === index ? { ...item, type: event.target.value } : item,
                        ),
                      })
                    }
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  >
                    {actionTypes.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                  {action.type.includes('tag') && action.type !== 'clear_tags' ? (
                    <div className="grid gap-2">
                      <select
                        value={action.tag_id ?? ''}
                        onChange={(event) =>
                          patchConfig({
                            actions: actions.map((item, idx) =>
                              idx === index ? { ...item, tag_id: event.target.value } : item,
                            ),
                          })
                        }
                        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                      >
                        <option value="">Выберите тег</option>
                        {tags.map((tag) => (
                          <option key={tag.id} value={tag.id}>
                            {tag.name}
                          </option>
                        ))}
                      </select>
                      <div className="flex gap-2">
                        <input
                          value={newTagName}
                          onChange={(event) => setNewTagName(event.target.value)}
                          placeholder="+ Создать тег"
                          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-xs text-gray-100 outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => void createTag()}
                          className="rounded-lg border border-white/10 px-2 text-xs text-gray-100"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  ) : null}
                  {action.type === 'set_lead_status' ? (
                    <select
                      value={action.status ?? ''}
                      onChange={(event) =>
                        patchConfig({
                          actions: actions.map((item, idx) =>
                            idx === index ? { ...item, status: event.target.value } : item,
                          ),
                        })
                      }
                      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                    >
                      <option value="">Выберите статус</option>
                      {statuses.map((status) => (
                        <option key={status.id} value={status.code ?? ''}>
                          {status.name ?? status.code}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  {action.type === 'write_field' ? (
                    <div className="grid gap-2">
                      <select
                        value={action.field ?? ''}
                        onChange={(event) =>
                          patchConfig({
                            actions: actions.map((item, idx) =>
                              idx === index ? { ...item, field: event.target.value } : item,
                            ),
                          })
                        }
                        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                      >
                        {leadFields.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                      <input
                        value={action.value ?? ''}
                        onChange={(event) =>
                          patchConfig({
                            actions: actions.map((item, idx) =>
                              idx === index ? { ...item, value: event.target.value } : item,
                            ),
                          })
                        }
                        placeholder="value"
                        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                      />
                    </div>
                  ) : null}
                  {action.type === 'submit_to_partner' ? (
                    <select
                      value={action.partner_integration_id ?? ''}
                      onChange={(event) =>
                        patchConfig({
                          actions: actions.map((item, idx) =>
                            idx === index ? { ...item, partner_integration_id: event.target.value } : item,
                          ),
                        })
                      }
                      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                    >
                      <option value="">Выберите partner CRM</option>
                      {partnerIntegrations.map((integration) => (
                        <option key={integration.id} value={integration.id}>
                          {integration.name}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => patchConfig({ actions: actions.filter((_, idx) => idx !== index) })}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-red-300/15 text-xs text-red-200"
                  >
                    Удалить действие
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          {step.block_type === 'generic_delay' ? (
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Тип ожидания
                </span>
                <select
                  value={textValue(step.config_json, 'delay_type') || 'wait'}
                  onChange={(event) => patchConfig({ delay_type: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  <option value="wait">Ждать и перейти дальше</option>
                  <option value="no_reply_timeout">Если нет ответа</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Задержка, сек</span>
                <input
                  type="number"
                  min={0}
                  value={numberValue(step.config_json, 'delay_seconds', 600)}
                  onChange={(event) => patchConfig({ delay_seconds: Number(event.target.value) || 0 })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Куда перейти</span>
                <TargetSelect
                  value={textValue(step.config_json, 'target_step_id')}
                  currentStepId={step.id}
                  steps={steps}
                  onChange={(value) => patchConfig({ target_step_id: value })}
                />
              </label>
            </div>
          ) : null}

          {step.step_type === 'operator' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Действие оператора
              </span>
              <select
                value={textValue(step.config_json, 'operator_action') || 'handoff'}
                onChange={(event) => patchConfig({ operator_action: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                <option value="handoff">Передать оператору</option>
                <option value="notify">Уведомить оператора</option>
                <option value="stop_bot">Остановить бота</option>
              </select>
            </label>
          ) : null}

          {step.step_type === 'integration' ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                URL
              </span>
              <input
                value={textValue(step.config_json, 'url')}
                onChange={(event) => patchConfig({ url: event.target.value })}
                placeholder="https://example.com/webhook"
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          ) : null}

          {step.step_type === 'finish' ? (
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Результат
                </span>
                <select
                  value={textValue(step.config_json, 'result') || 'stop'}
                  onChange={(event) => patchConfig({ result: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  <option value="stop">Остановить сценарий</option>
                  <option value="success">Успешно</option>
                  <option value="lost">Lost</option>
                  <option value="rejected">Rejected</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-200">
                <input
                  type="checkbox"
                  checked={boolValue(step.config_json, 'set_lead_status', true)}
                  onChange={(event) => patchConfig({ set_lead_status: event.target.checked })}
                />
                Обновить статус лида
              </label>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Outputs</p>
        {outputs.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">У блока нет исходящих связей.</p>
        ) : (
          <div className="mt-2 space-y-2">
            {outputs.map((output) => (
              <div
                key={output.key}
                className="flex items-center justify-between gap-2 rounded-lg border border-accent-300/15 bg-accent-300/5 px-3 py-2 text-xs text-accent-50"
              >
                <span className="truncate">{output.label}</span>
                <span className="shrink-0 text-gray-500">
                  {output.targetStepId
                    ? steps.find((item) => item.id === output.targetStepId)?.title ?? 'target'
                    : 'handle'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => setIsAdvancedOpen((value) => !value)}
        className="flex w-full items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-left text-xs text-gray-400"
      >
        <span>Advanced</span>
        <ChevronDown size={14} className={isAdvancedOpen ? 'rotate-180' : ''} />
      </button>
      {isAdvancedOpen ? (
        <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4 text-xs leading-5 text-gray-500">
          Block: {step.block_type} · Step: {step.step_type}
        </div>
      ) : null}
    </section>
  )
}
