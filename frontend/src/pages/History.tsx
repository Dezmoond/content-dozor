import { Badge, Card, Stack, Table, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getCases } from '../api'
import { useAuth } from '../auth/AuthContext'

export default function History() {
  const { isAdmin } = useAuth()
  const { data, isLoading } = useQuery({ queryKey: ['cases'], queryFn: getCases })

  return (
    <Stack>
      <Text size="xl" fw={600}>История</Text>
      <Text size="sm" c="dimmed">
        {isAdmin ? 'Все кейсы и их статусы' : 'Ваши проанализированные кейсы'}
      </Text>
      <Card withBorder padding={0} style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Кейс</Table.Th>
              <Table.Th>Статус</Table.Th>
              <Table.Th></Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {isLoading ? (
              <Table.Tr><Table.Td colSpan={3}>Загрузка…</Table.Td></Table.Tr>
            ) : (data || []).map((c: any) => (
              <Table.Tr key={c.id}>
                <Table.Td>{c.title}</Table.Td>
                <Table.Td><Badge size="sm">{c.status}</Badge></Table.Td>
                <Table.Td>
                  <Text component={Link} to={`/cases/${c.id}`} size="sm" c="blue.3">открыть</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  )
}
