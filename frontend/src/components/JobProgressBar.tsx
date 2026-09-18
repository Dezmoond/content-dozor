import { useEffect, useState } from 'react'
import { Alert, Badge, Card, Progress, Stack, Text } from '@mantine/core'
import { getJob } from '../api'
import JobTimingStats, { type TimingSummary } from './JobTimingStats'

export type JobInfo = {
  id: string
  status: string
  progress: number
  detail?: string | null
  result?: unknown
  celery_task_id?: string | null
  case_id?: string | null
  document_id?: string | null
}

type Props = {
  jobId: string
  onComplete?: (job: JobInfo) => void
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'gray',
  running: 'blue',
  success: 'green',
  failed: 'red',
}

export default function JobProgressBar({ jobId, onComplete }: Props) {
  const [job, setJob] = useState<JobInfo | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!jobId) return undefined
    let active = true

    const poll = async (): Promise<boolean> => {
      try {
        const data = await getJob(jobId) as JobInfo
        if (!active) return true
        setJob(data)
        setError('')
        if (data.status === 'success' || data.status === 'failed') {
          onComplete?.(data)
          return true
        }
        return false
      } catch (e: unknown) {
        if (active) setError(e instanceof Error ? e.message : 'Ошибка опроса задачи')
        return false
      }
    }

    poll().then((done) => { if (done) return })
    const timer = setInterval(async () => {
      const done = await poll()
      if (done) clearInterval(timer)
    }, 1000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [jobId, onComplete])

  if (!job && !error) {
    return (
      <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Text c="dimmed">Загрузка статуса задачи…</Text>
      </Card>
    )
  }

  if (error && !job) {
    return <Alert color="red">{error}</Alert>
  }

  if (!job) return null

  const result = job.result as { timing?: TimingSummary } | undefined
  const timing = result?.timing

  const done = job.status === 'success'
  const failed = job.status === 'failed'
  const running = job.status === 'running' || job.status === 'pending'

  return (
    <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
      <Stack gap="sm">
        <Stack gap={4}>
          <Text fw={600}>Прогресс анализа</Text>
          <Badge color={STATUS_COLOR[job.status] || 'gray'} variant="light">
            {job.status}
          </Badge>
        </Stack>
        <Progress
          value={job.progress ?? 0}
          animated={running}
          striped={running}
          color={failed ? 'red' : done ? 'green' : 'blue'}
          size="lg"
          radius="sm"
        />
        <Text size="sm" c="dimmed">
          {job.detail || (running ? 'Обработка…' : '')}
          {job.progress != null ? ` · ${job.progress}%` : ''}
        </Text>
        {done && (
          <Alert color="green" variant="light">
            Анализ завершён. Результаты сохранены в кейсе.
          </Alert>
        )}
        {done && timing && <JobTimingStats timing={timing} />}
        {failed && (
          <Alert color="red" variant="light">
            {job.detail || 'Задача завершилась с ошибкой'}
          </Alert>
        )}
      </Stack>
    </Card>
  )
}
