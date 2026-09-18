import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Alert, Badge, Button, Card, Group, Stack, Table, Tabs, Text, Title,
} from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteCase, fetchCaseHtmlReport, getCase } from '../api'
import JobTimingStats, { type TimingSummary } from '../components/JobTimingStats'

const SOURCE_LABEL: Record<string, string> = {
  docx: 'Документ DOCX',
  pdf: 'Документ PDF',
  paste: 'Вставленный текст',
  url: 'Ссылка / HTML',
  telegram: 'Telegram',
  vk: 'ВКонтакте',
}

const KIND_LABEL: Record<string, string> = {
  danger: 'опасное',
  blocklist: 'лексикон',
  registry: 'реестр',
  entity: 'сущность',
  shallow: 'поверхностный',
}

const TOOL_FALLBACK: Record<string, string> = {
  danger: 'Qwen Extremism (LLM)',
  blocklist: 'Запретный лексикон (WER)',
  registry: 'Реестр (CSV)',
  entity: 'Извлечение сущностей',
  shallow: 'Qwen Shallow (4 класса)',
}

const CLASS_LABEL: Record<string, string> = {
  extremist: 'Экстремистский (по закону РФ)',
  dangerous: 'Опасный / призыв к плохим действиям',
  provocative: 'Провокационный',
  negative: 'Вызывающий негативную реакцию',
}

function findingText(payload: any): string {
  if (!payload) return ''
  if (typeof payload === 'string') return payload
  // Совпадения реестра: красная пометка + реестр + строка
  if (payload.processor === 'registry_enrich' || payload.source_title || (payload.row != null && payload.match)) {
    const surface = String(payload.surface || payload.query || payload.entity || '')
    const match = String(payload.match || '')
    const title = String(payload.source_title || payload.source || 'реестр')
    const row = payload.row != null ? `строка ${payload.row}` : ''
    const bits = [title, row].filter(Boolean).join(', ')
    const head = surface || match
    const rest = match && match !== surface ? ` → ${match}` : ''
    return bits ? `${head}${rest} [${bits}]` : `${head}${rest}`
  }
  const text = String(payload.text || payload.match || payload.entity || payload.phrase || '')
  const reason = payload.reason ? ` — ${payload.reason}` : ''
  const cls = payload.class_label || CLASS_LABEL[payload.class] || ''
  if (cls && text) return `[${cls}] ${text}${reason}`
  return text || JSON.stringify(payload)
}

function findingConfidence(f: any): string {
  const p = f.payload || {}
  const raw = p.validation_confidence ?? p.confidence ?? (f.confidence != null ? Math.round(Number(f.confidence) * (Number(f.confidence) <= 1 ? 100 : 1)) : null)
  if (raw == null || Number.isNaN(Number(raw))) return '—'
  const n = Math.round(Number(raw))
  return `${n}%`
}

function findingTool(f: any): string {
  const p = f.payload || {}
  const tool = f.tool || p.tool || TOOL_FALLBACK[f.kind] || f.processor || p.processor || '—'
  const model = p.model ? ` · ${p.model}` : ''
  const scored = p.scored_by === 'qwen_validation' ? ' · проверено' : ''
  return `${tool}${model}${scored}`
}

function pickHtmlFromCase(data: any): string | null {
  const runs = data?.pipeline_runs || []
  for (const r of runs) {
    const hp = r?.result?.artifacts?.html_preview
    if (typeof hp === 'string' && hp.trim().length > 40 && !hp.includes('No HTML report')) {
      return hp
    }
  }
  return null
}

function triggerDownload(body: string, caseId: string) {
  const blob = new Blob([body], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `case-${caseId.slice(0, 8)}-report.html`
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

export default function CaseDetail() {
  const { caseId = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [html, setHtml] = useState<string | null>(null)
  const [htmlErr, setHtmlErr] = useState('')
  const [loadingHtml, setLoadingHtml] = useState(false)
  const [tab, setTab] = useState<string | null>('overview')
  const [deleting, setDeleting] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => getCase(caseId),
    enabled: !!caseId,
  })

  const embeddedHtml = useMemo(() => pickHtmlFromCase(data), [data])

  const timing: TimingSummary | null = useMemo(() => {
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      if (r.timing) return r.timing
      const art = r.result?.artifacts
      if (art?.timing) return art.timing
    }
    return null
  }, [data])

  const analysisMode = useMemo(() => {
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      const mode = r.pipeline_config?.analysis_mode
        || r.result?.artifacts?.analysis_mode
        || r.result?.result?.analysis_mode
      if (mode) return mode as string
    }
    return null
  }, [data])

  const ingestMeta = useMemo(() => {
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      const meta = r.result?.artifacts?.ingest_meta
      if (meta && typeof meta === 'object') return meta as Record<string, unknown>
    }
    const docs = data?.documents || []
    if (docs[0]?.meta && typeof docs[0].meta === 'object') return docs[0].meta as Record<string, unknown>
    return null
  }, [data])

  const natashaDebug = useMemo(() => {
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      const art = r.result?.artifacts
      if (!art) continue
      const has =
        art.natasha_entities != null
        || art.natasha_entities_typed != null
        || art.natasha_stats != null
      if (!has) continue
      const steps = r.steps_log || art.timing?.steps || []
      const step = Array.isArray(steps)
        ? steps.find((s: any) => s?.step === 'natasha_entities' || s?.id === 'natasha_entities')
        : null
      return {
        runId: r.id,
        stats: art.natasha_stats?.entities || art.natasha_stats || null,
        typed: art.natasha_entities_typed || null,
        raw: Array.isArray(art.natasha_entities) ? art.natasha_entities : [],
        step,
        stepsLog: steps,
      }
    }
    return null
  }, [data])

  const registryByEntity = useMemo(() => {
    const map = new Map<string, { title: string; row?: number; match?: string }>()
    const add = (key: string, hit: any) => {
      const k = key.trim().toLowerCase()
      if (!k || map.has(k)) return
      map.set(k, {
        title: String(hit.source_title || hit.source || 'реестр'),
        row: hit.row,
        match: hit.match,
      })
    }
    for (const f of data?.findings || []) {
      if (f.kind !== 'registry') continue
      const p = f.payload || {}
      add(String(p.surface || ''), p)
      add(String(p.query || ''), p)
      add(String(p.match || ''), p)
      add(String(p.entity || ''), p)
    }
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      for (const h of r.result?.artifacts?.registry_hits || []) {
        if (!h || typeof h !== 'object') continue
        add(String(h.surface || ''), h)
        add(String(h.query || ''), h)
        add(String(h.match || ''), h)
      }
    }
    return map
  }, [data])

  const entities = useMemo(() => {
    const runs = data?.pipeline_runs || []
    for (const r of runs) {
      const art = r.result?.artifacts
      if (!art) continue
      const qwen = art.entities
      const rubertTyped = art.rubert_entities_typed
      const natashaTyped = art.natasha_entities_typed
      if (qwen || rubertTyped || natashaTyped) {
        const mergeKey = (key: string) => {
          const a = (qwen?.[key] || []).map((e: any) => (typeof e === 'string' ? e : (e?.text || e?.normal))).filter(Boolean)
          const b = (rubertTyped?.[key] || []).map((e: any) => (typeof e === 'string' ? e : (e?.text || e?.normal))).filter(Boolean)
          const c = (natashaTyped?.[key] || []).map((e: any) => {
            if (typeof e === 'string') return e
            const surface = e?.text || ''
            const normal = e?.normal || ''
            if (surface && normal && surface !== normal) return `${surface} → ${normal}`
            return surface || normal
          }).filter(Boolean)
          return Array.from(new Set([...a, ...b, ...c]))
        }
        return {
          persons: mergeKey('persons'),
          organizations: mergeKey('organizations'),
          titles: mergeKey('titles'),
          urls: mergeKey('urls'),
        }
      }
      if (Array.isArray(art.rubert_entities) && art.rubert_entities.length) {
        const out: any = { persons: [], organizations: [], titles: [], urls: [] }
        for (const e of art.rubert_entities) {
          const t = e?.text
          if (!t) continue
          const lab = String(e.label || '')
          if (lab === 'fio' || lab === 'person') out.persons.push(t)
          else if (lab === 'organization') out.organizations.push(t)
          else if (lab === 'title') out.titles.push(t)
          else if (lab === 'url') out.urls.push(t)
        }
        return out
      }
    }
    return null
  }, [data])

  const resolveHtml = async (): Promise<string> => {
    if (html && html.trim()) return html
    if (embeddedHtml) return embeddedHtml
    return fetchCaseHtmlReport(caseId)
  }

  const loadHtml = async () => {
    setLoadingHtml(true)
    setHtmlErr('')
    try {
      const body = await resolveHtml()
      if (!body || body.includes('Нет HTML') || body.includes('No HTML')) {
        throw new Error('HTML-отчёт ещё не готов. Дождитесь завершения анализа.')
      }
      setHtml(body)
      setTab('text')
    } catch (e: unknown) {
      setHtmlErr(e instanceof Error ? e.message : 'Не удалось загрузить отчёт')
      setTab('text')
    } finally {
      setLoadingHtml(false)
    }
  }

  const downloadHtml = async () => {
    setHtmlErr('')
    try {
      const body = await resolveHtml()
      if (!body || body.includes('Нет HTML') || body.includes('No HTML')) {
        throw new Error('HTML-отчёт ещё не готов. Дождитесь завершения анализа.')
      }
      setHtml(body)
      triggerDownload(body, caseId)
    } catch (e: unknown) {
      setHtmlErr(e instanceof Error ? e.message : 'Не удалось скачать отчёт')
      setTab('text')
    }
  }

  const onDelete = async () => {
    if (!window.confirm(`Удалить кейс «${data?.case?.title || caseId}»? Документ и результаты будут удалены.`)) return
    setDeleting(true)
    try {
      await deleteCase(caseId)
      await qc.invalidateQueries({ queryKey: ['cases'] })
      navigate('/cases')
    } catch (e: unknown) {
      setHtmlErr(e instanceof Error ? e.message : 'Не удалось удалить кейс')
    } finally {
      setDeleting(false)
    }
  }

  if (isLoading) return <Text c="dimmed">Загрузка кейса…</Text>
  if (error) return <Alert color="red">{(error as Error).message}</Alert>
  if (!data) return null

  const c = data.case
  const findings = data.findings || []
  const shownHtml = html || embeddedHtml

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Button component={Link} to="/cases" variant="subtle" size="xs" mb={4}>← К списку</Button>
          <Title order={2}>{c.title}</Title>
          <Group gap="sm" mt={6}>
            <Badge>{c.status}</Badge>
            {analysisMode && (
              <Badge color={analysisMode === 'shallow' ? 'violet' : 'blue'} variant="light">
                {analysisMode === 'shallow' ? 'поверхностный анализ' : 'глубокий анализ'}
              </Badge>
            )}
            {c.owner_email && <Text size="sm" c="dimmed">автор: {c.owner_email}</Text>}
            <Text size="xs" c="dimmed" ff="monospace">{c.id}</Text>
          </Group>
        </div>
        <Group>
          <Button variant="light" onClick={loadHtml} loading={loadingHtml}>Показать разметку</Button>
          <Button onClick={downloadHtml}>Скачать HTML</Button>
          <Button variant="light" color="red" loading={deleting} onClick={onDelete}>Удалить кейс</Button>
        </Group>
      </Group>

      <Tabs value={tab} onChange={setTab}>
        <Tabs.List>
          <Tabs.Tab value="overview">Обзор</Tabs.Tab>
          <Tabs.Tab value="findings">Находки ({findings.length})</Tabs.Tab>
          <Tabs.Tab value="entities">Сущности</Tabs.Tab>
          <Tabs.Tab value="natasha">Natasha (тест)</Tabs.Tab>
          <Tabs.Tab value="timing">Статистика</Tabs.Tab>
          <Tabs.Tab value="text">Текст</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          <Stack>
            <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
              <Text fw={600} mb="sm">Источник</Text>
              {(data.documents || []).length === 0 ? (
                <Text c="dimmed">Нет источника</Text>
              ) : (
                <Table>
                  <Table.Tbody>
                    {data.documents.map((d: any) => (
                      <Table.Tr key={d.id}>
                        <Table.Td>{d.filename}</Table.Td>
                        <Table.Td>
                          <Badge size="sm" variant="light">
                            {SOURCE_LABEL[d.source_type] || d.source_type}
                          </Badge>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
              {ingestMeta && (
                <Stack gap={4} mt="sm">
                  {ingestMeta.url ? (
                    <Text size="sm" c="dimmed">URL: {String(ingestMeta.url)}</Text>
                  ) : null}
                  {ingestMeta.preview_url ? (
                    <Text size="sm" c="dimmed">превью: {String(ingestMeta.preview_url)}</Text>
                  ) : null}
                  {ingestMeta.posts_count != null ? (
                    <Text size="sm" c="dimmed">
                      постов: {String(ingestMeta.posts_count)}
                      {ingestMeta.comments_count != null ? ` · комментариев: ${String(ingestMeta.comments_count)}` : ''}
                    </Text>
                  ) : null}
                  {ingestMeta.chars != null ? (
                    <Text size="sm" c="dimmed">символов: {String(ingestMeta.chars)}</Text>
                  ) : null}
                  {Array.isArray(ingestMeta.warnings) && ingestMeta.warnings.map((w: any, i: number) => (
                    <Text key={i} size="sm" c="orange">{String(w)}</Text>
                  ))}
                </Stack>
              )}
            </Card>
            <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
              <Text fw={600} mb="sm">Прогоны пайплайна</Text>
              {(data.pipeline_runs || []).map((r: any) => (
                <Group key={r.id} justify="space-between" mb={6}>
                  <Text size="sm" ff="monospace">{r.id.slice(0, 8)}</Text>
                  <Badge size="sm">{r.status}</Badge>
                  <Text size="sm" c="dimmed">{r.timing?.total_human || r.finished_at || '—'}</Text>
                </Group>
              ))}
            </Card>
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="findings" pt="md">
          <Card withBorder padding={0} style={{ background: '#161B22', borderColor: '#30363D' }}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Тип</Table.Th>
                  <Table.Th>Инструмент</Table.Th>
                  <Table.Th>Уверенность</Table.Th>
                  <Table.Th>Текст / совпадение</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {findings.length === 0 ? (
                  <Table.Tr><Table.Td colSpan={4}>Находок нет</Table.Td></Table.Tr>
                ) : findings.map((f: any) => (
                  <Table.Tr key={f.id}>
                    <Table.Td>
                      <Badge size="sm" color={
                        f.kind === 'danger' || f.kind === 'registry' ? 'red'
                          : f.kind === 'blocklist' ? 'orange'
                          : f.kind === 'entity' ? 'teal'
                          : 'blue'
                      }>
                        {KIND_LABEL[f.kind] || f.kind}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{findingTool(f)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={f.kind === 'danger' || f.kind === 'registry' ? 600 : 400}>{findingConfidence(f)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text
                        size="sm"
                        c={f.kind === 'registry' ? 'red' : undefined}
                        fw={f.kind === 'registry' ? 600 : undefined}
                      >
                        {findingText(f.payload)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="entities" pt="md">
          <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
            {!entities ? (
              <Text c="dimmed">Сущности ещё не извлечены</Text>
            ) : (
              <Stack>
                {(['persons', 'organizations', 'titles', 'urls'] as const).map((key) => (
                  <div key={key}>
                    <Text fw={600} mb={4}>{key}</Text>
                    <ul style={{ margin: 0 }}>
                      {(entities[key] || []).length === 0 && <li><Text c="dimmed" size="sm">пусто</Text></li>}
                      {(entities[key] || []).map((e: any, i: number) => {
                        const label = typeof e === 'string' ? e : (e.text || '')
                        const base = label.split(' → ')[0].trim().toLowerCase()
                        const hit = registryByEntity.get(base)
                          || registryByEntity.get(label.trim().toLowerCase())
                        const meta = hit
                          ? ` [${hit.title}${hit.row != null ? `, строка ${hit.row}` : ''}]`
                          : ''
                        return (
                          <li key={i}>
                            <Text
                              span
                              size="sm"
                              c={hit ? 'red' : undefined}
                              fw={hit ? 600 : undefined}
                            >
                              {label}{meta}
                            </Text>
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                ))}
              </Stack>
            )}
          </Card>
        </Tabs.Panel>

        <Tabs.Panel value="natasha" pt="md">
          <Stack>
            <Alert color="yellow">
              Временный тестовый вывод Natasha. Если ошибка «No module named natasha» —
              пакет не был в Python сервиса (уже ставится в Python 3.10). Перезапустите анализ кейса.
            </Alert>
            {!natashaDebug ? (
              <Text c="dimmed">В артефактах прогона нет данных Natasha (шаг не запускался или старый прогон).</Text>
            ) : (
              <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
                <Stack>
                  <Text fw={600}>Статистика</Text>
                  <Text size="sm" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(natashaDebug.stats || { note: 'stats пусто' }, null, 2)}
                  </Text>
                  {natashaDebug.stats?.error && (
                    <Alert color="red">Ошибка загрузки/работы: {String(natashaDebug.stats.error)}</Alert>
                  )}
                  <Text fw={600}>Шаг пайплайна</Text>
                  <Text size="sm" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                    {natashaDebug.step
                      ? JSON.stringify(natashaDebug.step, null, 2)
                      : 'запись natasha_entities в steps_log не найдена (возможно, шаг выключен в «Методы»)'}
                  </Text>
                  <Text fw={600}>Typed (persons / organizations / urls)</Text>
                  <Text size="sm" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(natashaDebug.typed || {}, null, 2)}
                  </Text>
                  <Text fw={600}>Сырой список ({natashaDebug.raw.length})</Text>
                  {natashaDebug.raw.length === 0 ? (
                    <Text c="dimmed" size="sm">пусто — Natasha ничего не извлекла или не загрузилась</Text>
                  ) : (
                    <Table striped>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>label</Table.Th>
                          <Table.Th>text (в документе)</Table.Th>
                          <Table.Th>normal / ФИО канон</Table.Th>
                          <Table.Th>слоты</Table.Th>
                          <Table.Th>span</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {natashaDebug.raw.map((e: any, i: number) => (
                          <Table.Tr key={i}>
                            <Table.Td>{e.label}</Table.Td>
                            <Table.Td>{e.text}</Table.Td>
                            <Table.Td>
                              {e.fio_normalized || e.normal || '—'}
                              {e.fio_source ? <Text size="xs" c="dimmed">{e.fio_source}</Text> : null}
                            </Table.Td>
                            <Table.Td>
                              <Text size="xs" ff="monospace">
                                {e.fio_parts
                                  ? `ф=${e.fio_parts.surname || '—'}; и=${e.fio_parts.name || '—'}; о=${e.fio_parts.patronymic || '—'}`
                                  : '—'}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Text size="xs" ff="monospace">{e.start}–{e.end}</Text>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  )}
                  {(data?.pipeline_runs || []).some((r: any) => r.result?.artifacts?.fio_normalized) && (
                    <>
                      <Text fw={600} mt="md">fio_normalized (после шага RuBERT FIO / слоты)</Text>
                      <Text size="sm" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                        {JSON.stringify(
                          (data.pipeline_runs.find((r: any) => r.result?.artifacts?.fio_normalized)
                            ?.result?.artifacts?.fio_normalized || []).map((x: any) => ({
                            text: x.text,
                            fio: x.fio_normalized,
                            parts: x.fio_parts,
                            src: x.fio_source,
                          })),
                          null,
                          2,
                        )}
                      </Text>
                    </>
                  )}
                </Stack>
              </Card>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="timing" pt="md">
          {timing ? <JobTimingStats timing={timing} /> : <Text c="dimmed">Статистика времени появится после успешного анализа</Text>}
        </Tabs.Panel>

        <Tabs.Panel value="text" pt="md">
          <Stack>
            {htmlErr && <Alert color="red">{htmlErr}</Alert>}
            {!shownHtml && (
              <Alert color="gray">
                Нажмите «Показать разметку», чтобы открыть размеченный текст с выделениями и ссылками.
                {embeddedHtml ? '' : ' Если анализ уже завершён, отчёт подтянется из результатов прогона.'}
              </Alert>
            )}
            {shownHtml && (
              <Card withBorder padding={0} style={{ background: '#0F1419', borderColor: '#30363D', overflow: 'hidden' }}>
                <iframe
                  title="case-report"
                  srcDoc={shownHtml}
                  sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
                  style={{ width: '100%', minHeight: 640, border: 0, background: '#0f1419' }}
                />
              </Card>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
