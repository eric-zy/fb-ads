const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

const source = fs.readFileSync('src/utils/dateTime.ts', 'utf8')
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const functions = {}
vm.runInNewContext(output, { exports: functions, Date, Number, String })
const { formatDateTime, parseDateTime, formatDateTimeCell } = functions
const originalTimezone = process.env.TZ
try {
  process.env.TZ = 'Asia/Shanghai'
  assert.equal(formatDateTime('2026-10-07T01:02:03.654321'), '2026-10-07 09:02:03')
  assert.equal(formatDateTime('2026-10-07T01:02:03.999999Z'), '2026-10-07 09:02:03')
  assert.equal(formatDateTime('2026-10-07T09:02:03+08:00'), '2026-10-07 09:02:03')
  assert.equal(formatDateTime('2026-10-07 01:02:03'), '2026-10-07 09:02:03')
  assert.equal(formatDateTime('2026-10-07'), '2026-10-07')
  assert.equal(formatDateTime(null, '暂无登录记录'), '暂无登录记录')
  assert.equal(formatDateTime('invalid'), '-')
  assert.equal(parseDateTime('invalid'), null)
  assert.equal(parseDateTime('2026-10-07T09:02:03+08:00').toISOString(), '2026-10-07T01:02:03.000Z')
  assert.equal(formatDateTimeCell({}, {}, '2026-10-07T01:02:03'), '2026-10-07 09:02:03')
  process.env.TZ = 'America/New_York'
  assert.equal(formatDateTime('2026-07-07T01:02:03Z'), '2026-07-06 21:02:03')
  assert.equal(formatDateTime('2026-01-07T01:02:03Z'), '2026-01-06 20:02:03')
  console.log('PASS dates: UTC, explicit offsets, microseconds, null/invalid values, date-only fields, table cells and DST')
} finally {
  if (originalTimezone === undefined) delete process.env.TZ
  else process.env.TZ = originalTimezone
}
