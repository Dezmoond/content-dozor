import { useEffect, useState } from 'react'
import { Button, Card, NumberInput, Stack, Text, TextInput } from '@mantine/core'
import { getSettings, putSetting } from '../api'

export default function Models() {
  const [models, setModels] = useState<Record<string, unknown>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings().then((s) => setModels((s.models as Record<string, unknown>) || {}))
  }, [])

  const save = async () => {
    await putSetting('models', models)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Stack>
      <Text size="xl" fw={600}>Модели</Text>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          <TextInput label="Extremism (llama.cpp)" value={String(models.extremism_model || '')} onChange={(e) => setModels({ ...models, extremism_model: e.target.value })} />
          <TextInput label="Entities (llama.cpp)" value={String(models.entities_model || '')} onChange={(e) => setModels({ ...models, entities_model: e.target.value })} />
          <TextInput label="Validation (llama.cpp)" value={String(models.validation_model || '')} onChange={(e) => setModels({ ...models, validation_model: e.target.value })} />
          <NumberInput label="Temperature" value={Number(models.temperature) || 0.2} step={0.1} min={0} max={2} onChange={(v) => setModels({ ...models, temperature: v })} />
          <NumberInput label="Max tokens" value={Number(models.max_tokens) || 512} onChange={(v) => setModels({ ...models, max_tokens: v })} />
          <NumberInput label="Chunk size" value={Number(models.chunk_size) || 300} onChange={(v) => setModels({ ...models, chunk_size: v })} />
          <Button onClick={save}>{saved ? 'Сохранено' : 'Сохранить'}</Button>
        </Stack>
      </Card>
    </Stack>
  )
}
