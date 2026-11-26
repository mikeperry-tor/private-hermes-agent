// Verify the actual packaged renderer inputs before patching, not a reference checkout.
import { readFileSync } from 'node:fs'
import { sourceHash } from '/opt/hermes/scripts/build/freshness.mjs'
const stamp = JSON.parse(readFileSync('/opt/hermes/install-stamp.json', 'utf8'))
if (stamp.commit !== '8fc0374447313e276f6b9a2764bfc750190c966a' || stamp.dirty !== false) {
  throw new Error('Private Hermes patches require the pinned clean upstream source')
}
const expected = 'b70656c6a129f5b4172aa6b388e1e8991a5301eeff8b4d0a3bf8d09aeff04801'
const receipt = JSON.parse(readFileSync('/opt/hermes/apps/desktop/dist-webapp/hermes-build.json', 'utf8'))
if (receipt.product !== 'webapp' || receipt.inputs.sourceHash !== expected ||
    sourceHash('/opt/hermes', 'webapp') !== expected) {
  throw new Error('Packaged Webapp source does not match the reviewed build inputs')
}
