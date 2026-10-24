"""Example local transform (stdlib only), speaking the same stdin/argv protocol as maltego-trx.

Maltego / OSINT Graph invoke:  python dns_to_ip_local.py <entity value> [k=v#k2=v2]
and read a <MaltegoMessage> from stdout. Register it in the UI: Transforms -> Add local ->
  command: python   args: examples/dns_to_ip_local.py   input: Domain
A real maltego-trx project registers the same way:  args: project.py local dnstoip   (working dir = project)
"""
import socket, sys
from xml.sax.saxutils import escape

value = sys.argv[1]
ents, msgs = [], []
try:
    for ip in sorted({a[4][0] for a in socket.getaddrinfo(value, None)}):
        ents.append(f'<Entity Type="maltego.IPv4Address"><Value>{escape(ip)}</Value><Weight>100</Weight>'
                    f'<AdditionalFields><Field Name="link#maltego.link.label" DisplayName="Label">'
                    f'Resolves To (local)</Field></AdditionalFields></Entity>')
except OSError as e:
    msgs.append(f'<UIMessage MessageType="PartialError">{escape(str(e))}</UIMessage>')

print(f"<MaltegoMessage><MaltegoTransformResponseMessage><Entities>{''.join(ents)}</Entities>"
      f"<UIMessages>{''.join(msgs)}</UIMessages></MaltegoTransformResponseMessage></MaltegoMessage>")
