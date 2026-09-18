import { Card, Stack, Table, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { getAudit } from '../api'

export default function Logs() {
  const { data, isLoading } = useQuery({ queryKey: ['audit'], queryFn: getAudit })
  return (
    <Stack>
      <Text size="xl" fw={600}>Аудит</Text>
      <Card withBorder padding={0} style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Table striped>
          <Table.Thead>
            <Table.Tr><Table.Th>Действие</Table.Th><Table.Th>Processor</Table.Th><Table.Th>Модель</Table.Th><Table.Th>Кейс</Table.Th></Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading ? (
              <Table.Tr><Table.Td colSpan={4}>Загрузка…</Table.Td></Table.Tr>
            ) : (data || []).map((r: any) => (
              <Table.Tr key={r.id}>
                <Table.Td>{r.action}</Table.Td>
                <Table.Td>{r.processor_id || '—'}</Table.Td>
                <Table.Td>{r.model_name || '—'}</Table.Td>
                <Table.Td><Text size="xs" ff="monospace">{r.case_id?.slice(0, 8) || '—'}</Text></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  )
}
