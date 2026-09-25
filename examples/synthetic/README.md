# Synthetic examples

Run the generator with the project environment:

```powershell
python generate.py
geofvbridge inspect generated/two_prisms.msh
geofvbridge convert generated/two_prisms.msh
geofvbridge export eco2m generated/two_prisms.geofv.h5 --config eco2m.json
```

The source mesh contains two triangles. GeoFVBridge extrudes them into two
wedge cells that share one quadrilateral face. The expected total volume is
`1.0`, the number of internal connections is `1`, and the connection is
orthogonal.
