# Legal notes (not legal advice)

This project is a non-commercial hobby effort to add features to an instrument its users own.
It is designed so that **no NUX or Dream code or data is distributed**:

| Distributed here | Not distributed |
|---|---|
| tools (patcher, assembler, disassembler, porting helper) written from scratch | firmware files (`.bin`), modified or not |
| maps of addresses with our own descriptions, one per supported firmware file | generated listings (`.s`) of the firmware |
| patches: our instructions + short `expect` checks; web data: only the words our patches write | NUX updater, Dream documentation, sound banks, styles |

Users obtain the official firmware from NUX themselves, and the tools only work on that exact file
(SHA-256 check). The listing produced by `disasm` contains the vendor's code and is for the user's own
local work only.

**Interoperability.** In the EU, Directive 2009/24/EC (art. 5(3) and 6) and its national implementations
(e.g. art. 75 of the Polish copyright act) allow a lawful user to observe, study and test a program,
and under strict conditions to decompile it to achieve interoperability, without the right holder's
permission. Information obtained that way must not be used to create a competing program or be given to
others beyond what is necessary. We kept the published information to the minimum needed to apply the
patches.

**Trademarks.** "NUX", "NEK-100", "NEK-110" and "Dream" are used only to say which device and chip this works with.
This project is not affiliated with, authorised or endorsed by NUX or Dream.

**Warranty.** Modified firmware may void your warranty. Everything is provided "as is" (see LICENSE).
Flashing the official file restores the original firmware.

**Takedown / contact.** If you represent NUX or Dream and have a concern, please open an issue; we will
respond promptly. We would also gladly see these features in an official update.
