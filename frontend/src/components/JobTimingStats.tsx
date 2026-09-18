import { Card, Stack, Table, Text, Title } from '@mantine/core'

export type TimingStep = {
  step_id: string
  label: string
  status: string
  duration_ms: number
  duration_human: string
  detail?: unknown
}

export type TimingSummary = {
  total_ms?: number
  total_human?: string
  worker_total_ms?: number
  worker_total_human?: string
  steps_total_ms?: number
  model_load_total_ms?: number
  model_load_total_human?: string
  steps?: TimingStep[]
  model_loads?: Array<{
    role: string
    gguf?: string
    duration_ms: number
    duration_human?: string
    reused?: boolean
  }>
  chunk_stats?: Record<string, {
    chunks_processed?: number
    chunks_total?: number
    inference_ms?: number
    phase_ms?: number
  }>
}

type Props = {
  timing?: TimingSummary | null
  title?: string
}

export default function JobTimingStats({ timing, title = 'Статистика времени' }: Props) {
  if (!timing?.steps?.length) return null

  const total = timing.worker_total_human || timing.total_human || '—'

  return (
    <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
      <Stack gap="sm">
        <Title order={5}>{title}</Title>
        <Text size="sm">
          Итого по задаче: <Text span fw={700}>{total}</Text>
          {timing.model_load_total_human && timing.model_load_total_ms ? (
            <> · загрузка моделей: <Text span fw={600}>{timing.model_load_total_human}</Text></>
          ) : null}
        </Text>
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Шаг</Table.Th>
              <Table.Th>Время</Table.Th>
              <Table.Th>Статус</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {timing.steps.map((s) => (
              <Table.Tr key={s.step_id}>
                <Table.Td>{s.label}</Table.Td>
                <Table.Td>{s.duration_human}</Table.Td>
                <Table.Td>{s.status}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {timing.model_loads && timing.model_loads.length > 0 && (
          <>
            <Text size="sm" fw={600} mt="xs">Загрузка GGUF на GPU</Text>
            <Table withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Модель</Table.Th>
                  <Table.Th>Время</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {timing.model_loads.map((m, i) => (
                  <Table.Tr key={`${m.role}-${i}`}>
                    <Table.Td>{m.role}{m.reused ? ' (уже в VRAM)' : ''}</Table.Td>
                    <Table.Td>{m.reused ? '—' : (m.duration_human || `${m.duration_ms} мс`)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
        {timing.chunk_stats && Object.keys(timing.chunk_stats).length > 0 && (
          <>
            <Text size="sm" fw={600} mt="xs">Qwen по фазам (чанки)</Text>
            <Table withTableBorder>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Фаза</Table.Th>
                  <Table.Th>Чанков</Table.Th>
                  <Table.Th>Инференс</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {Object.entries(timing.chunk_stats).map(([phase, st]) => (
                  <Table.Tr key={phase}>
                    <Table.Td>{phase}</Table.Td>
                    <Table.Td>{st.chunks_processed}/{st.chunks_total}</Table.Td>
                    <Table.Td>{st.inference_ms != null ? `${(st.inference_ms / 1000).toFixed(1)} с` : '—'}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )}
      </Stack>
    </Card>
  )
}
