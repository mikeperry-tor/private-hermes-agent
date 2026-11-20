// Verify the actual packaged renderer inputs before patching, not a reference checkout.
import { readFileSync } from 'node:fs'
import { sourceHash } from '/opt/hermes/scripts/build/freshness.mjs'
const stamp = JSON.parse(readFileSync('/opt/hermes/install-stamp.json', 'utf8'))
if (stamp.commit !== 'caafe5389ae585ef77387a962aee05b1bcf17029' || stamp.dirty !== false) {
  throw new Error('Private Hermes patches require the pinned clean upstream source')
}
const expected = '03efd94d420bfdd70ea477a985c14fc56574e265e6e1a0f6cf601a33d07ec8af'
const receipt = JSON.parse(readFileSync('/opt/hermes/apps/desktop/dist-webapp/hermes-build.json', 'utf8'))
if (receipt.product !== 'webapp' || receipt.inputs.sourceHash !== expected ||
    sourceHash('/opt/hermes', 'webapp') !== expected) {
  throw new Error('Packaged Webapp source does not match the reviewed build inputs')
}
