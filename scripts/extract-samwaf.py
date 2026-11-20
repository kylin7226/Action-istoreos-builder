#!/usr/bin/env python3
import shutil
import sys
import tarfile

with tarfile.open(sys.argv[1], 'r:gz') as archive:
    binaries = [entry for entry in archive.getmembers()
                if entry.isfile() and entry.name.rsplit('/', 1)[-1].startswith('SamWafLinux')]
    if len(binaries) != 1:
        raise SystemExit('Expected exactly one SamWafLinux binary')
    with archive.extractfile(binaries[0]) as source, open(sys.argv[2], 'wb') as destination:
        shutil.copyfileobj(source, destination)
