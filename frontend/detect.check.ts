// Run: node detect.check.ts
import assert from 'node:assert'
import { detectType } from './src/types.ts'

const cases: Record<string, string> = {
  'https://example.com/a?b=1': 'URL', 'bob@mail.example.org': 'EmailAddress', '8.8.8.8': 'IPAddress',
  '2001:db8::1': 'IPAddress', '+1 (555) 010-0199': 'PhoneNumber', 'sub.example.co.uk': 'Domain',
  'torvalds': 'Phrase', '2024-01-01': 'Phrase', '999.1.1.1': 'Phrase', 'Jane Doe': 'Phrase', '12:30:00': 'Phrase',
}
for (const [v, t] of Object.entries(cases)) assert.equal(detectType(v), t, v)
console.log('ok')
