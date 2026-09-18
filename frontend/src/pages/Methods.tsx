import { useEffect, useState } from 'react'
import { Button, Card, Checkbox, Stack, Text } from '@mantine/core'
import { getSettings, putSetting } from '../api'

const STEP_LABELS: Record<string, string> = {
  ingest_docx: 'Извлечение текста источника',
  chunk_text: 'Чанкинг текста',
  qwen_entities: 'Qwen — сущности',
  qwen_extremism: 'Qwen — опасные фразы',
  qwen_validation: 'Qwen — проверка ложных срабатываний',
  rubert_entities: 'RuBERT — сущности',
  rubert_danger: 'RuBERT — опасность',
  rubert_fio: 'RuBERT FIO — слоты (фамилия имя отчество / инициалы)',
  natasha_entities: 'Natasha — ФИО / организации / URL (без titles; NamesExtractor + именительный)',
  registry_enrich: 'Сверка с реестрами',
  blocklist_lexicon: 'Запретный лексикон',
  report_json: 'Формирование JSON-отчёта',
}

/** Шаги, которые нельзя отключить (каркас пайплайна). */
const LOCKED_ON = new Set(['ingest_docx', 'chunk_text', 'report_json'])

export default function Methods() {
  const [steps, setSteps] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings().then((s) => {
      const p = (s.pipeline as any) || {}
      const raw = { ...(p.enabled_steps || {}) }
      // Поверхностный шаг управляется режимом при загрузке документа, не галочкой здесь
      delete raw.qwen_shallow
      setSteps(raw)
    })
  }, [])

  const toggle = (k: string) => {
    if (LOCKED_ON.has(k)) return
    setSteps((prev) => ({ ...prev, [k]: !(prev[k] !== false) }))
  }

  const save = async () => {
    const enabled_steps = { ...steps, qwen_shallow: false }
    for (const k of LOCKED_ON) enabled_steps[k] = true
    await putSetting('pipeline', { enabled_steps })
    setSteps(enabled_steps)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <Stack>
      <Text size="xl" fw={600}>Методы обработки</Text>
      <Text size="sm" c="dimmed">
        Эти шаги применяются при <Text span fw={600}>глубоком</Text> анализе.
        Первый шаг извлекает текст из выбранного источника (DOCX, PDF, вставка, ссылка, Telegram, VK).
        Поверхностный режим использует фиксированный короткий пайплайн (4 класса на validation-Qwen).
        Имена моделей, temperature, max tokens и размер чанка — на странице «Модели».
      </Text>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          {Object.entries(STEP_LABELS).map(([k, label]) => (
            <Checkbox
              key={k}
              label={label + (LOCKED_ON.has(k) ? ' (обязательно)' : '')}
              checked={steps[k] !== false}
              disabled={LOCKED_ON.has(k)}
              onChange={() => toggle(k)}
            />
          ))}
          <Button onClick={save} mt="md">{saved ? 'Сохранено' : 'Сохранить'}</Button>
        </Stack>
      </Card>
    </Stack>
  )
}
