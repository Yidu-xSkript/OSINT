"""Machine (multi-phase transform pipeline) definitions, mirrored from frontend/src/machines.ts.
Used by the monitor scheduler, which runs machines without the UI. Kept in sync by hand (only 3)."""

MACHINES = {
    "domain-footprint": {"id": "domain-footprint", "name": "Domain Footprint", "inputType": "Domain", "phases": [
        {"steps": [{"transform": "crtsh", "limit": 500}, {"transform": "dns-mx"}, {"transform": "dns-ns"},
                   {"transform": "domain-website"}, {"transform": "rdap"}]},
        {"steps": [{"transform": "dns-a"}]},
        {"steps": [{"transform": "ip-geo"}, {"transform": "ip-ptr"}]}]},
    "username-to-person": {"id": "username-to-person", "name": "Username to Person", "inputType": "Phrase", "phases": [
        {"steps": [{"transform": "phrase-github"}]},
        {"steps": [{"transform": "affiliation-github"}]}]},
    "url-recon": {"id": "url-recon", "name": "Web Page Recon", "inputType": "URL", "phases": [
        {"steps": [{"transform": "url-snapshot"}, {"transform": "url-intel"}, {"transform": "url-domain"}]},
        {"steps": [{"transform": "dns-a"}]}]},
}
