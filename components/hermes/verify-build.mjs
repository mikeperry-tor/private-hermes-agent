// Verify the actual packaged renderer inputs before patching, not a reference checkout.
import { readFileSync } from 'node:fs'
import { sourceHash } from '/opt/hermes/scripts/build/freshness.mjs'
const stamp = JSON.parse(readFileSync('/opt/hermes/install-stamp.json', 'utf8'))
if (stamp.commit !== 'ae2a81ccc00e9b7c06301523e5bb09608397149c' || stamp.dirty !== false) {
  throw new Error('Private Hermes patches require the pinned clean upstream source')
}
const expected = 'cf2671eb38ea4d06789e81e06d5648d946c82229f3ee90db912cc7f287a72373'
const receipt = JSON.parse(readFileSync('/opt/hermes/apps/desktop/dist-webapp/hermes-build.json', 'utf8'))
if (receipt.product !== 'webapp' || receipt.inputs.sourceHash !== expected ||
    sourceHash('/opt/hermes', 'webapp') !== expected) {
  throw new Error('Packaged Webapp source does not match the reviewed build inputs')
}
