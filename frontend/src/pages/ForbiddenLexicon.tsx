import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, NumberInput, Stack, Text, Textarea,
} from '@mantine/core'
import { getSettings, putSetting } from '../api'

const DEFAULT_PHRASES = ['facebook', 'meta', '1488']
const DEFAULT_MAX_WER = 0.25

type ForbiddenLexicon = {
  phrases: string[]
  max_wer: number
}

function toTextarea(phrases: string[]) {
  return phrases.join('\n')
}

function fromTextarea(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
}

export default function ForbiddenLexiconPage() {
  const [phrasesText, setPhrasesText] = useState(toTextarea(DEFAULT_PHRASES))
  const [maxWer, setMaxWer] = useState(DEFAULT_MAX_WER)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getSettings()
      .then((s) => {
        const cfg = (s.forbidden_lexicon as ForbiddenLexicon) || {}
        const phrases = Array.isArray(cfg.phrases) && cfg.phrases.length
          ? cfg.phrases
          : DEFAULT_PHRASES
        setPhrasesText(toTextarea(phrases))
        setMaxWer(typeof cfg.max_wer === 'number' ? cfg.max_wer : DEFAULT_MAX_WER)
      })
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    const phrases = fromTextarea(phrasesText)
    await putSetting('forbidden_lexicon', {
      phrases,
      max_wer: maxWer,
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const phraseCount = fromTextarea(phrasesText).length

  return (
    <Stack>
      <Text size="xl" fw={600}>Запретный лексикон</Text>
      <Alert color="blue" variant="light">
        Общий список для всех пользователей. Фразы ищутся в документе по WER (допускаются
        опечатки). Одна фраза — одна строка; многословные фразы пишите через пробел.
        Строки с # — комментарии.
      </Alert>
      <Card withBorder padding="lg" style={{ background: '#161B22', borderColor: '#30363D' }}>
        <Stack>
          <Textarea
            label="Запрещённые слова и фразы"
            description={`Сейчас в списке: ${phraseCount}`}
            minRows={12}
            value={phrasesText}
            onChange={(e) => setPhrasesText(e.currentTarget.value)}
            disabled={loading}
            styles={{ input: { fontFamily: 'monospace' } }}
            placeholder={'facebook\nmeta\n1488\nслава руси'}
          />
          <NumberInput
            label="Порог WER (0 = только точное совпадение, 0.25 = ~75% совпадения слов)"
            min={0}
            max={1}
            step={0.05}
            decimalScale={2}
            value={maxWer}
            onChange={(v) => setMaxWer(typeof v === 'number' ? v : DEFAULT_MAX_WER)}
            disabled={loading}
          />
          <Button onClick={save} mt="md" disabled={loading}>
            {saved ? 'Сохранено' : 'Сохранить для всех'}
          </Button>
        </Stack>
      </Card>
    </Stack>
  )
}
