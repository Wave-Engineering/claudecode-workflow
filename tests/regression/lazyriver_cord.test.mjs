// lazyriver_cord.test.mjs — unit test for the coded escalation cord (#844).
// The cord is the load-bearing loop-guard: the sufficiency CALL is the agent's
// judgment, but the CORD (leg-cap | 2 consecutive zero-finding legs) is enforced
// by river.js#cordCheck. Run via tests/regression/test_lazyriver_cord.sh.
import { cordCheck } from '../../skills/lazyriver/river.js'

let fail = 0
const eq = (got, want, name) => {
  if (got !== want) {
    console.error(`  [FAIL] ${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)
    fail = 1
  } else {
    console.log(`  [PASS] ${name}`)
  }
}

eq(cordCheck({ legNum: 1, maxLegs: 10, consecutiveZeroFindings: 0 }), null, 'fresh loop keeps going')
eq(cordCheck({ legNum: 10, maxLegs: 10, consecutiveZeroFindings: 0 }), null, 'leg 10 (== cap) still runs')
eq(cordCheck({ legNum: 11, maxLegs: 10, consecutiveZeroFindings: 0 }), 'cord:leg-cap', 'leg 11 > cap → leg-cap')
eq(cordCheck({ legNum: 3, maxLegs: 10, consecutiveZeroFindings: 1 }), null, '1 zero-finding leg is not enough')
eq(cordCheck({ legNum: 3, maxLegs: 10, consecutiveZeroFindings: 2 }), 'cord:diminishing', '2 consecutive zero-finding → diminishing')
eq(cordCheck({ legNum: 11, maxLegs: 10, consecutiveZeroFindings: 2 }), 'cord:leg-cap', 'leg-cap wins when both trigger')

process.exit(fail)
