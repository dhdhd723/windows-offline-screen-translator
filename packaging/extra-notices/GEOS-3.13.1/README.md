# GEOS 3.13.1 LGPL notices and corresponding source

Shapely 2.1.2 in this portable package uses the GEOS 3.13.1 shared libraries.
The LGPL-2.1 text is included at:
`LICENSES/Shapely/shapely-2.1.2.dist-info/licenses/LICENSE_GEOS`.

The complete upstream source archive is distributed alongside the binaries in
`LICENSES/upstream/GEOS-3.13.1/geos-3.13.1.tar.bz2`. The public source repository
contains this README and build recipes; the large GEOS archive is a portable
package asset and is deliberately not copied into the application's Git source
export.

Official source archive:
https://download.osgeo.org/geos/geos-3.13.1.tar.bz2

Archive SHA-256:
`df2c50503295f325e7c8d7b783aca8ba4773919cde984193850cf9e361dfd28c`.

The exact Shapely release and Windows GEOS build recipes are retained as text:

- https://raw.githubusercontent.com/shapely/shapely/2.1.2/.github/workflows/release.yml
- https://raw.githubusercontent.com/shapely/shapely/2.1.2/ci/install_geos.cmd

The fixed release recipe selects GEOS 3.13.1. Its Windows recipe directly
downloads and compiles this source as shared libraries; it does not patch the
GEOS source. Wheel repair adjusts bundled DLL filenames and import references.
The source package includes its copyright notices, LGPL text and build files.

The libraries remain separate under `_internal/Shapely.libs`. Compatible
modified versions may be substituted after closing the application; bundle
repair filenames and the ABI must be preserved or adjusted consistently with
the Shapely extension. The application imposes no restrictions on reverse
engineering for debugging modifications to these LGPL libraries. Intel and
Microsoft component-specific terms do not replace GEOS's LGPL rights.
