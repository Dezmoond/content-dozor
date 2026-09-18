import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert, Badge, Button, Card, Group, Radio, Stack, Table, Text, TextInput,
} from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createCase, deleteCase, getCases, getIngestSources, ingestSource } from '../api'
import { useAuth } from '../auth/AuthContext'
import JobProgressBar from '../components/JobProgressBar'
import SourcePicker, {
  defaultCaseTitle,
  defaultSourceDraft,
  resolveSources,
  sourceReady,
  type SourceDraft,
} from '../components/SourcePicker'

const STATUS_LABEL: Record<string, string> = {
  new: 'новый',
  processing: 'в работе',
  review: 'готово',
  failed: 'ошибка',
  closed: 'закрыт',
}

const STATUS_COLOR: Record<string, string> = {
  new: 'gray',
  processing: 'blue',
  review: 'green',
  failed: 'red',
  closed: 'dark',
}

export default function Cases() {
  const [title, setTitle] = useState('')
  const [source, setSource] = useState<SourceDraft>(defaultSourceDraft)
  const [jobId, setJobId] = useState<string | null>(null)
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null)
  const [analysisMode, setAnalysisMode] = useState<'deep' | 'shallow'>('deep')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAdmin, user } = useAuth()
  const { data, isLoading } = useQuery({ queryKey: ['cases'], queryFn: getCases })
  const { data: ingestCatalog } = useQuery({ queryKey: ['ingest-sources'], queryFn: getIngestSources })
  const sourceItems = resolveSources(ingestCatalog?.items)
  const selectedSpec = sourceItems.find((s) => s.id === source.sourceType) || sourceItems[0]
  const canSubmit = sourceReady(source, selectedSpec, ingestCatalog?.online)

  const cases = useMemo(() => data || [], [data])

  const onCreateAndAnalyze = async () => {
    if (!canSubmit) {
      setError('Укажите источник для анализа')
      return
    }
    setLoading(true)
    setError('')
    setJobId(null)
    setCreatedCaseId(null)
    try {
      const created: any = await createCase(title.trim() || defaultCaseTitle(source))
      const caseId = created.id as string
      setCreatedCaseId(caseId)
      const res = await ingestSource(caseId, {
        sourceType: source.sourceType,
        analysisMode: analysisMode,
        file: source.file,
        text: source.text,
        url: source.url,
        includeComments: source.includeComments,
      })
      qc.invalidateQueries({ queryKey: ['cases'] })
      const id = res?.job?.id as string | undefined
      if (id) setJobId(id)
      else if (res?.queue_error) setError(`Очередь недоступна: ${res.queue_error}`)
      else setError('Кейс создан, но задача анализа не поставлена')
      setTitle('')
      setSource(defaultSourceDraft())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка создания кейса')
    } finally {
      setLoading(false)
    }
  }

  const onDelete = async (id: string, caseTitle: string) => {
    if (!window.confirm(`Удалить кейс «${caseTitle}»? Документ и результаты будут удалены.`)) return
    setDeletingId(id)
    setError('')
    try {
      await deleteCase(id)
      if (createdCaseId === id) {
        setCreatedCaseId(null)
        setJobId(null)
      }
      await qc.invalidateQueries({ queryKey: ['cases'] })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось удалить кейс')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Text size="xl" fw={600}>Кейсы</Text>
          <Text size="sm" c="dimmed">
            {isAdmin ? 'Все кейсы платформы (админ)' : `Ваши кейсы · ${user?.email}`}
          </Text>
        </div>
      </Group>

      <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          <Text fw={600}>Новый кейс</Text>
          <Text size="sm" c="dimmed">
            Выберите тип источника, метод анализа и название. В один кейс — один источник;
            для другого материала создайте новый кейс. Telegram и VK будем расширять
            (полный сбор комментариев через API).
          </Text>
          <TextInput
            label="Название"
            placeholder="Например: Читинский район — проверка"
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
          />
          <SourcePicker
            value={source}
            onChange={setSource}
            sources={sourceItems}
            online={ingestCatalog?.online}
          />
          <Radio.Group
            label="Метод анализа"
            description={
              analysisMode === 'deep'
                ? 'Шаги из «Методы», параметры из «Модели» / запретный лексикон'
                : 'Короткий пайплайн (4 класса); модели и чанки — из «Модели»'
            }
            value={analysisMode}
            onChange={(v) => setAnalysisMode(v as 'deep' | 'shallow')}
          >
            <Stack gap={6} mt={6}>
              <Radio
                value="deep"
                label="Глубокий — по настройкам «Методы»"
              />
              <Radio
                value="shallow"
                label="Поверхностный — 4 класса фраз (Qwen validation)"
              />
            </Stack>
          </Radio.Group>
          <Button onClick={onCreateAndAnalyze} loading={loading} disabled={!canSubmit}>
            Создать и запустить анализ
          </Button>
          {error && <Alert color="red">{error}</Alert>}
          {jobId && (
            <Stack gap={6}>
              <JobProgressBar
                jobId={jobId}
                onComplete={() => {
                  qc.invalidateQueries({ queryKey: ['cases'] })
                }}
              />
              {createdCaseId && (
                <Button variant="light" onClick={() => navigate(`/cases/${createdCaseId}`)}>
                  Открыть кейс
                </Button>
              )}
            </Stack>
          )}
        </Stack>
      </Card>

      <Card withBorder padding={0} style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Название</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th>ID</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading ? (
              <Table.Tr><Table.Td colSpan={4}>Загрузка…</Table.Td></Table.Tr>
            ) : cases.length === 0 ? (
              <Table.Tr><Table.Td colSpan={4}>Нет кейсов</Table.Td></Table.Tr>
            ) : cases.map((c: any) => (
              <Table.Tr
                key={c.id}
                style={{ cursor: 'pointer' }}
                onDoubleClick={() => navigate(`/cases/${c.id}`)}
              >
                <Table.Td>{c.title}</Table.Td>
                <Table.Td>
                  <Badge size="sm" color={STATUS_COLOR[c.status] || 'gray'}>
                    {STATUS_LABEL[c.status] || c.status}
                  </Badge>
                </Table.Td>
                <Table.Td><Text size="xs" ff="monospace">{c.id.slice(0, 8)}</Text></Table.Td>
                <Table.Td>
                  <Group gap={6} justify="flex-end" wrap="nowrap">
                    <Button
                      size="xs"
                      variant="light"
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/cases/${c.id}`)
                      }}
                    >
                      Открыть
                    </Button>
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      loading={deletingId === c.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        onDelete(c.id, c.title)
                      }}
                    >
                      Удалить
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="xs" c="dimmed" p="sm">Двойной клик — открыть детали кейса</Text>
      </Card>
    </Stack>
  )
}
