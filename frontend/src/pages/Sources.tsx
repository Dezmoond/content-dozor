import { useState } from 'react'
import { Button, Card, Select, Stack, Text, Code } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { getParsers, runParser } from '../api'

export default function Sources() {
  const [parserId, setParserId] = useState<string | null>('minjust_extremist_materials')
  const [result, setResult] = useState<any>(null)
  const { data } = useQuery({ queryKey: ['parsers'], queryFn: getParsers })

  const items = (data?.items || []).length
    ? data.items
    : (data?.parsers || []).map((p: string) => ({ id: p, name: p }))

  const onRun = async () => {
    if (!parserId) return
    const res = await runParser(parserId)
    setResult(res)
  }

  return (
    <Stack>
      <Text size="xl" fw={600}>Источники</Text>
      <Text size="sm" c="dimmed">
        Госреестры (local_parsers / parser_zapret). Прогон пишется в{' '}
        <Code>analysis_platform/data/parser_runs/YYYY-MM-DD/</Code>, затем валидные CSV
        применяются в <Code>analysis_platform/data/blacklist/</Code>. Файл{' '}
        <Code>rknweb_blocked_sites.csv</Code> только пополняется отсутствующими строками.
        Проблемы (пусто / &lt;20 строк / нет файла) — в{' '}
        <Code>data/blacklist/update_logs/</Code>.
      </Text>
      <Text size="sm" c="dimmed">
        Внешний Tkinter: <Code>cd local_parsers</Code> → <Code>python run_gui.py</Code> —
        только папки по датам; в приложение копируйте вручную. CLI платформы:{' '}
        <Code>python run_gui.py --cli minjust_extremist_materials --output ..\analysis_platform\data\parser_runs --apply-app</Code>
      </Text>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          <Select
            label="Источник"
            data={items.map((p: { id: string; name: string }) => ({
              value: p.id,
              label: p.name,
            }))}
            value={parserId}
            onChange={setParserId}
            searchable
          />
          <Button onClick={onRun}>Запустить (очередь)</Button>
        </Stack>
      </Card>
      {result && (
        <Card withBorder padding="md" style={{ background: '#161B22', borderColor: '#30363D' }}>
          <Code block>{JSON.stringify(result, null, 2)}</Code>
        </Card>
      )}
    </Stack>
  )
}
