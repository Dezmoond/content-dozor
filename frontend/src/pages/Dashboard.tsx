import { Card, Grid, Group, Text, Badge, Loader, Stack } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { getCases } from '../api'

async function health() {
  const h = await fetch('/health')
  if (h.ok) return h.json()
  return { status: 'unknown' }
}

export default function Dashboard() {
  const { data, isLoading } = useQuery({ queryKey: ['health'], queryFn: health, refetchInterval: 30000 })
  const { data: cases } = useQuery({ queryKey: ['cases'], queryFn: getCases })
  return (
    <Stack>
      <Text size="xl" fw={600}>Dashboard</Text>
      <Grid>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card padding="lg" radius="md" withBorder style={{ background: '#161B22', borderColor: '#30363D' }}>
            <Text c="dimmed" size="sm">Кейсов</Text>
            <Text size="xl" fw={700}>{cases?.length ?? '—'}</Text>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Card padding="lg" radius="md" withBorder style={{ background: '#161B22', borderColor: '#30363D' }}>
            <Group justify="space-between" mb="sm">
              <Text fw={600}>Статус сервисов</Text>
              {isLoading && <Loader size="sm" />}
            </Group>
            <Grid>
              {data?.downstream && Object.entries(data.downstream).map(([k, v]: [string, any]) => (
                <Grid.Col span={4} key={k}>
                  <Badge color={v.status === 'ok' ? 'teal' : 'red'} variant="light" fullWidth>{k}</Badge>
                </Grid.Col>
              ))}
            </Grid>
          </Card>
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
