import type { EntityType } from './types'

// Modelled on Maltego machines (automation/*.machine, MSL): phases run in order; the transforms in a phase run in
// parallel ("paths"), each on every entity of its input type found so far in this run. limit = MSL "slider".
export interface Machine {
  id: string
  name: string
  inputType: EntityType
  description: string
  phases: { status: string; steps: { transform: string; limit?: number }[] }[]
}

export const MACHINES: Machine[] = [
  {
    id: 'domain-footprint',
    name: 'Domain Footprint',
    inputType: 'Domain',
    description: 'DNS + certificate-log enumeration, resolve hosts, then geolocate IPs and find their networks (like Footprint L1).',
    phases: [
      { status: 'DNS enumeration', steps: [{ transform: 'crtsh', limit: 500 }, { transform: 'dns-mx' }, { transform: 'dns-ns' }, { transform: 'domain-website' }, { transform: 'rdap' }] },
      { status: 'Resolve hostnames', steps: [{ transform: 'dns-a' }] },
      { status: 'Networks and owners', steps: [{ transform: 'ip-geo' }, { transform: 'ip-ptr' }] },
    ],
  },
  {
    id: 'username-to-person',
    name: 'Username to Person',
    inputType: 'Phrase',
    description: 'Find the GitHub account for a username, then expand its public profile.',
    phases: [
      { status: 'Account lookup', steps: [{ transform: 'phrase-github' }] },
      { status: 'Profile details', steps: [{ transform: 'affiliation-github' }] },
    ],
  },
  {
    id: 'url-recon',
    name: 'Web Page Recon',
    inputType: 'URL',
    description: 'Snapshot the page, extract contacts and linked sites, then resolve the host.',
    phases: [
      { status: 'Page', steps: [{ transform: 'url-snapshot' }, { transform: 'url-intel' }, { transform: 'url-domain' }] },
      { status: 'Hosts', steps: [{ transform: 'dns-a' }] },
    ],
  },
]
