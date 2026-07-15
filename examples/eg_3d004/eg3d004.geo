

//------------------start-------------------//
// Gmsh project created on 2025.8.3
SetFactory("OpenCASCADE");

//三裂隙三维模型 场地大小（xyz方向各一条裂隙）
//x=1000.0;
//y=1000.0;
//z=400.0;

dms=50; //mesh size 默认网格的剖分尺寸
dx1=50; //X line the first fracture long
dy1=50; //Y line the first fracture long
dz1=50; //Z line the first fracture long


x1=100.0; //x方向第一个裂隙点位置，z=0
x2=600.0; //x方向第一个裂隙点位置，z=400.0

y1=100.0; //y方向第一个裂隙点位置，z=0
y2=600.0; //y方向第一个裂隙点位置，z=400.0处

z1=100.0; //z方向第一个裂隙点位置，x=0
z2=300.0; //z方向第一个裂隙点位置，x=1000.0

//+++++++++++++++++++++++++++++++++++++++++++++++++++++++
//+点前设置
Gradx=x2-x1;
Grady=y2-y1;
Gradz=z2-z1;
Denom=400000.0-Gradz*Gradx;
Point1x=(1000.0*(z1*Gradx+400.0*x1))/Denom;  //y=0.0以及y=1000.0的xz面上需要的4交点的参数
Point2x=(1000*((z1+dz1)*Gradx+400*x1))/Denom;
Point3x=(1000*(z1*Gradx+400*(x1+dx1)))/Denom;
Point4x=(1000*((z1+dz1)*Gradx+400*(x1+dx1)))/Denom;


//+点

Point(1)={(1000.0*(z1*Gradx+400.0*x1))/Denom, 0.0, Gradz*Point1x/1000.0+z1, dms}; //y=0.0的xz面上的4交点
Point(2)={(1000*((z1+dz1)*Gradx+400*x1))/Denom, 0.0, Gradz*Point2x/1000+z1+dz1, dms};
Point(3)={(1000*(z1*Gradx+400*(x1+dx1)))/Denom, 0.0, Gradz*Point3x/1000+z1, dms};
Point(4)={(1000*((z1+dz1)*Gradx+400*(x1+dx1)))/Denom, 0.0, Gradz*Point4x/1000+z1+dz1, dms};

Point(5)={(1000.0*(z1*Gradx+400.0*x1))/Denom, 1000.0, Gradz*Point1x/1000.0+z1, dms};  //y=1000.0的xz面上的4交点
Point(6)={(1000*((z1+dz1)*Gradx+400*x1))/Denom, 1000.0, Gradz*Point2x/1000+z1+dz1, dms};
Point(7)={(1000*(z1*Gradx+400*(x1+dx1)))/Denom, 1000.0, Gradz*Point3x/1000+z1, dms};
Point(8)={(1000*((z1+dz1)*Gradx+400*(x1+dx1)))/Denom, 1000.0, Gradz*Point4x/1000+z1+dz1, dms};

Point(9)={1000.0, y1+z2*(y2-y1)/400, z2, dms};  //X=1000.0的yz面上的4交点
Point(10)={1000.0, y1+(z2+dz1)*(y2-y1)/400, z2+dz1, dms};
Point(11)={1000.0, y1+dy1+z2*(y2-y1)/400, z2, dms};
Point(12)={1000.0, y1+dy1+(z2+dz1)*(y2-y1)/400, z2+dz1, dms};


Point(13)={0.0, y1+z1*(y2-y1)/400, z1, dms};  //X=0.0 的yz面上的4交点
Point(14)={0.0, y1+(z1+dz1)*(y2-y1)/400, z1+dz1, dms};
Point(15)={0.0, y1+dy1+z1*(y2-y1)/400, z1, dms};
Point(16)={0.0, y1+dy1+(z1+dz1)*(y2-y1)/400, z1+dz1, dms};


Point(17)={x2, y2, 400.0, dms};  //z=400.0的xy面上的4交点
Point(18)={x2+dx1, y2, 400.0, dms};
Point(19)={x2+dx1, y2+dy1, 400.0, dms};
Point(20)={x2, y2+dy1, 400.0, dms};

Point(21)={x1, y1, 0.0, dms};  //z=0.0的xy面上的4交点
Point(22)={x1+dx1, y1, 0.0, dms};
Point(23)={x1+dx1, y1+dy1, 0.0, dms};
Point(24)={x1, y1+dy1, 0.0, dms};

//+三个面的交点，共8个
Point(25)={(400000*(x1+dx1)+1000*Gradx*(z1+dz1))/Denom, y1+(Grady*(Gradz*(x1+dx1)+1000*(z1+dz1)))/Denom, (400*(Gradz*(x1+dx1)+1000*(z1+dz1)))/Denom, dms};
Point(26)={(400000*(x1+dx1)+1000*Gradx*z1)/Denom, y1+(Grady*(Gradz*(x1+dx1)+1000*z1))/Denom, (400*(Gradz*(x1+dx1)+1000*z1))/Denom, dms};
Point(27)={(400000*(x1+dx1)+1000*Gradx*(z1+dz1))/Denom, y1+dy1+(Grady*(Gradz*(x1+dx1)+1000*(z1+dz1)))/Denom, (400*(Gradz*(x1+dx1)+1000*(z1+dz1)))/Denom, dms};
Point(28)={(400000*(x1+dx1)+1000*Gradx*z1)/Denom, y1+dy1+(Grady*(Gradz*(x1+dx1)+1000*z1))/Denom, (400*(Gradz*(x1+dx1)+1000*z1))/Denom, dms};
Point(29)={(400000*x1+1000*Gradx*(z1+dz1))/Denom, y1+dy1+(Grady*(Gradz*x1+1000*(z1+dz1)))/Denom, (400*(Gradz*x1+1000*(z1+dz1)))/Denom, dms};
Point(30)={(400000*x1+1000*Gradx*z1)/Denom, y1+dy1+(Grady*(Gradz*x1+1000*z1))/Denom, (400*(Gradz*x1+1000*z1))/Denom, dms};
Point(31)={(400000*x1+1000*Gradx*(z1+dz1))/Denom, y1+(Grady*(Gradz*x1+1000*(z1+dz1)))/Denom, (400*(Gradz*x1+1000*(z1+dz1)))/Denom, dms};
Point(32)={(400000*x1+1000*Gradx*z1)/Denom, y1+(Grady*(Gradz*x1+1000*z1))/Denom, (400*(Gradz*x1+1000*z1))/Denom, dms};


//+整个框架的点
//+点设置
Point(33)={0.0, 0.0, 0.0, dms};//底层z=0.0点位
Point(34)={x1, 0.0, 0.0, dms};
Point(35)={x1+dx1, 0.0, 0.0, dms};
Point(36)={1000.0, 0.0, 0.0, dms};
Point(37)={1000.0, y1, 0.0, dms};
Point(38)={1000.0, y1+dy1, 0.0, dms};
Point(39)={1000.0, 1000.0, 0.0, dms};
Point(40)={x1+dx1, 1000.0, 0.0, dms};
Point(41)={x1, 1000.0, 0.0, dms};
Point(42)={0.0, 1000.0, 0.0, dms};
Point(43)={0.0, y1+dy1, 0.0, dms};
Point(44)={0.0, y1, 0.0, dms};

Point(45)={0.0, 0.0, z1, dms};//中层z=z1,z2点位
Point(46)={1000.0, 0.0, z2, dms};
Point(47)={1000.0, 1000.0, z2, dms};
Point(48)={0.0, 1000.0, z1, dms};
Point(49)={0.0, 0.0, z1+dz1, dms};//中层z=z1+dz1,z2+dz1点位
Point(50)={1000.0, 0.0, z2+dz1, dms};
Point(51)={1000.0, 1000.0, z2+dz1, dms};
Point(52)={0.0, 1000.0, z1+dz1, dms};

Point(53)={0.0, 0.0, 400.0, dms};//底层z=400.0点位
Point(54)={x2, 0.0, 400.0, dms};
Point(55)={x2+dx1, 0.0, 400.0, dms};
Point(56)={1000.0, 0.0, 400.0, dms};
Point(57)={1000.0, y2, 400.0, dms};
Point(58)={1000.0, y2+dy1, 400.0, dms};
Point(59)={1000.0, 1000.0, 400.0, dms};
Point(60)={x2+dx1, 1000.0, 400.0, dms};
Point(61)={x2, 1000.0, 400.0, dms};
Point(62)={0.0, 1000.0, 400.0, dms};
Point(63)={0.0, y2+dy1, 400.0, dms};
Point(64)={0.0, y2, 400.0, dms};



//+线
Line(1) = {33, 34};
//+
Line(2) = {34, 35};
//+
Line(3) = {35, 36};
//+
Line(4) = {36, 37};
//+
Line(5) = {37, 38};
//+
Line(6) = {38, 39};
//+
Line(7) = {39, 40};
//+
Line(8) = {40, 41};
//+
Line(9) = {41, 42};
//+
Line(10) = {42, 43};
//+
Line(11) = {43, 44};
//+
Line(12) = {44, 33};
//+
Line(13) = {33, 45};
//+
Line(14) = {45, 49};
//+
Line(15) = {49, 53};
//+
Line(16) = {53, 64};
//+
Line(17) = {64, 63};
//+
Line(18) = {63, 62};
//+
Line(19) = {62, 61};
//+
Line(20) = {61, 60};
//+
Line(21) = {60, 59};
//+
Line(22) = {59, 58};
//+
Line(23) = {58, 57};
//+
Line(24) = {57, 56};
//+
Line(25) = {56, 55};
//+
Line(26) = {55, 54};
//+
Line(27) = {54, 53};
//+
Line(28) = {36, 46};
//+
Line(29) = {46, 50};
//+
Line(30) = {50, 56};
//+
Line(31) = {39, 47};
//+
Line(32) = {47, 51};
//+
Line(33) = {51, 59};
//+
Line(34) = {42, 48};
//+
Line(35) = {48, 52};
//+
Line(36) = {52, 62};
//+
Line(37) = {45, 1};
//+
Line(38) = {1, 34};
//+
Line(39) = {35, 3};
//+
Line(40) = {3, 46};
//+
Line(41) = {49, 2};
//+
Line(42) = {2, 54};
//+
Line(43) = {55, 4};
//+
Line(44) = {4, 50};
//+
Line(45) = {46, 9};
//+
Line(46) = {9, 37};
//+
Line(47) = {38, 11};
//+
Line(48) = {11, 47};
//+
Line(49) = {50, 10};
//+
Line(50) = {10, 57};
//+
Line(51) = {58, 12};
//+
Line(52) = {12, 51};
//+
Line(53) = {51, 8};
//+
Line(54) = {8, 60};
//+
Line(55) = {61, 6};
//+
Line(56) = {6, 52};
//+
Line(57) = {40, 7};
//+
Line(58) = {7, 47};
//+
Line(59) = {41, 5};
//+
Line(60) = {5, 48};
//+
Line(61) = {48, 15};
//+
Line(62) = {15, 43};
//+
Line(63) = {44, 13};
//+
Line(64) = {13, 45};
//+
Line(65) = {52, 16};
//+
Line(66) = {16, 63};
//+
Line(67) = {64, 14};
//+
Line(68) = {14, 49};
//+
Line(69) = {54, 17};
//+
Line(70) = {17, 64};
//+
Line(71) = {63, 20};
//+
Line(72) = {20, 61};
//+
Line(73) = {60, 19};
//+
Line(74) = {19, 58};
//+
Line(75) = {57, 18};
//+
Line(76) = {18, 55};
//+
Line(77) = {31, 17};
//+
Line(78) = {31, 2};
//+
Line(79) = {31, 14};
//+
Line(80) = {25, 18};
//+
Line(81) = {25, 4};
//+
Line(82) = {25, 10};
//+
Line(83) = {27, 19};
//+
Line(84) = {27, 12};
//+
Line(85) = {27, 8};
//+
Line(86) = {29, 20};
//+
Line(87) = {29, 6};
//+
Line(88) = {29, 16};
//+
Line(89) = {32, 13};
//+
Line(90) = {32, 1};
//+
Line(91) = {32, 21};
//+
Line(92) = {26, 9};
//+
Line(93) = {26, 3};
//+
Line(94) = {26, 22};
//+
Line(95) = {28, 11};
//+
Line(96) = {28, 7};
//+
Line(97) = {28, 23};
//+
Line(98) = {30, 5};
//+
Line(99) = {30, 15};
//+
Line(100) = {30, 24};
//+
Line(101) = {37, 22};
//+
Line(102) = {22, 35};
//+
Line(103) = {34, 21};
//+
Line(104) = {21, 44};
//+
Line(105) = {43, 24};
//+
Line(106) = {24, 41};
//+
Line(107) = {40, 23};
//+
Line(108) = {23, 38};


//+面

//+
Curve Loop(1) = {1, -38, -37, -13};
//+
Plane Surface(1) = {1};
//+
Curve Loop(2) = {3, 28, -40, -39};
//+
Plane Surface(2) = {2};
//+
Curve Loop(3) = {15, -27, -42, -41};
//+
Plane Surface(3) = {3};
//+
Curve Loop(4) = {43, 44, 30, 25};
//+
Plane Surface(4) = {4};
//+
Curve Loop(5) = {2, 39, 40, 29, -44, -43, 26, -42, -41, -14, 37, 38};
//+
Plane Surface(5) = {5};
//+
Curve Loop(6) = {4, -46, -45, -28};
//+
Plane Surface(6) = {6};
//+
Curve Loop(7) = {6, 31, -48, -47};
//+
Plane Surface(7) = {7};
//+
Curve Loop(8) = {52, 33, 22, 51};
//+
Plane Surface(8) = {8};
//+
Curve Loop(9) = {49, 50, 24, -30};
//+
Plane Surface(9) = {9};
//+
Curve Loop(10) = {5, 47, 48, 32, -52, -51, 23, -50, -49, -29, 45, 46};
//+
Plane Surface(10) = {10};
//+
Curve Loop(11) = {7, 57, 58, -31};
//+
Plane Surface(11) = {11};
//+
Curve Loop(12) = {9, 34, -60, -59};
//+
Plane Surface(12) = {12};
//+
Curve Loop(13) = {56, 36, 19, 55};
//+
Plane Surface(13) = {13};
//+
Curve Loop(14) = {53, 54, 21, -33};
//+
Plane Surface(14) = {14};
//+
Curve Loop(15) = {8, 59, 60, 35, -56, -55, 20, -54, -53, -32, -58, -57};
//+
Plane Surface(15) = {15};
//+
Curve Loop(16) = {10, -62, -61, -34};
//+
Plane Surface(16) = {16};
//+
Curve Loop(17) = {12, 13, -64, -63};
//+
Plane Surface(17) = {17};
//+
Curve Loop(18) = {68, 15, 16, 67};
//+
Plane Surface(18) = {18};
//+
Curve Loop(19) = {65, 66, 18, -36};
//+
Plane Surface(19) = {19};
//+
Curve Loop(20) = {11, 63, 64, 14, -68, -67, 17, -66, -65, -35, 61, 62};
//+
Plane Surface(20) = {20};
//+
Curve Loop(21) = {27, 16, -70, -69};
//+
Plane Surface(21) = {21};
//+
Curve Loop(22) = {25, -76, -75, 24};
//+
Plane Surface(22) = {22};
//+
Curve Loop(23) = {22, -74, -73, 21};
//+
Plane Surface(23) = {23};
//+
Curve Loop(24) = {19, -72, -71, 18};
//+
Plane Surface(24) = {24};
//+
Curve Loop(25) = {26, 69, 70, 17, 71, 72, 20, 73, 74, 23, 75, 76};
//+
Plane Surface(25) = {25};
//+
Curve Loop(26) = {70, 67, -79, 77};
//+
Plane Surface(26) = {26};
//+
Curve Loop(27) = {82, 50, 75, -80};
//+
Plane Surface(27) = {27};
//+
Curve Loop(28) = {51, -84, 83, 74};
//+
Plane Surface(28) = {28};
//+
Curve Loop(29) = {86, -71, -66, -88};
//+
Plane Surface(29) = {29};
//+
Curve Loop(30) = {54, 73, -83, 85};
//+
Plane Surface(30) = {30};
//+
Curve Loop(31) = {72, 55, -87, 86};
//+
Plane Surface(31) = {31};
//+
Curve Loop(32) = {77, -69, -42, -78};
//+
Plane Surface(32) = {32};
//+
Curve Loop(33) = {76, 43, -81, 80};
//+
Plane Surface(33) = {33};
//+
Curve Loop(34) = {56, 65, -88, 87};
//+
Plane Surface(34) = {34};
//+
Curve Loop(35) = {68, 41, -78, 79};
//+
Plane Surface(35) = {35};
//+
Curve Loop(36) = {44, 49, -82, 81};
//+
Plane Surface(36) = {36};
//+
Curve Loop(37) = {52, 53, -85, 84};
//+
Plane Surface(37) = {37};
//+
Curve Loop(38) = {37, -90, 89, 64};
//+
Plane Surface(38) = {38};
//+
Curve Loop(39) = {40, 45, -92, 93};
//+
Plane Surface(39) = {39};
//+
Curve Loop(40) = {48, -58, -96, 95};
//+
Plane Surface(40) = {40};
//+
Curve Loop(41) = {60, 61, -99, 98};
//+
Plane Surface(41) = {41};
//+
Curve Loop(42) = {90, 38, 103, -91};
//+
Plane Surface(42) = {42};
//+
Curve Loop(43) = {39, -93, 94, 102};
//+
Plane Surface(43) = {43};
//+
Curve Loop(44) = {101, -94, 92, 46};
//+
Plane Surface(44) = {44};
//+
Curve Loop(45) = {108, 47, -95, 97};
//+
Plane Surface(45) = {45};
//+
Curve Loop(46) = {57, -96, 97, -107};
//+
Plane Surface(46) = {46};
//+
Curve Loop(47) = {106, 59, -98, 100};
//+
Plane Surface(47) = {47};
//+
Curve Loop(48) = {105, -100, 99, 62};
//+
Plane Surface(48) = {48};
//+
Curve Loop(49) = {91, 104, 63, -89};
//+
Plane Surface(49) = {49};
//+
Curve Loop(50) = {1, 103, 104, 12};
//+
Plane Surface(50) = {50};
//+
Curve Loop(51) = {3, 4, 101, 102};
//+
Plane Surface(51) = {51};
//+
Curve Loop(52) = {6, 7, 107, 108};
//+
Plane Surface(52) = {52};
//+
Curve Loop(53) = {9, 10, 105, 106};
//+
Plane Surface(53) = {53};
//+
Curve Loop(54) = {2, -102, -101, 5, -108, -107, 8, -106, -105, 11, -104, -103};
//+
Plane Surface(54) = {54};
//+

//+体积

Surface Loop(1) = {50, 1, 17, 38, 42, 49};
Volume(1) = {1};


//+
Surface Loop(2) = {51, 2, 6, 39, 44, 43};
//+
Volume(2) = {2};
//+
Surface Loop(3) = {52, 7, 11, 40, 46, 45};
//+
Volume(3) = {3};
//+
Surface Loop(4) = {53, 12, 16, 41, 48, 47};
//+
Volume(4) = {4};
//+
Surface Loop(5) = {26, 35, 32, 21, 3, 18};
//+
Volume(5) = {5};
//+
Surface Loop(6) = {22, 4, 9, 36, 27, 33};
//+
Volume(6) = {6};
//+
Surface Loop(7) = {23, 8, 14, 37, 30, 28};
//+
Volume(7) = {7};
//+
Surface Loop(8) = {24, 13, 19, 34, 29, 31};
//+
Volume(8) = {8};
//+
Surface Loop(9) = {5, 54, 10, 15, 20, 25, 30, 28, 37, 31, 34, 29, 41, 48, 47, 38, 42, 49, 39, 44, 43, 40, 46, 45, 26, 35, 32, 33, 36, 27};
//+
Volume(9) = {9};
//+
Physical Surface("left", 109) = {19, 18, 20, 16, 17};
//+
Physical Surface("right", 110) = {9, 8, 7, 6, 10};
//+
Physical Surface("bottom", 111) = {50, 51, 52, 53, 54};
//+
Physical Surface("top", 112) = {24, 23, 22, 21, 25};
//+
Physical Surface("fracture", 113) = {41, 34, 47, 46, 40, 37, 45, 44, 39, 36, 43, 42, 38, 35, 49, 48, 30, 31, 29, 26, 32, 33, 27, 28};
//+
Physical Volume("Rocka", 114) = {8, 7, 6, 5, 3, 4, 1, 2};
//+
Physical Volume("Rockb", 115) = {9};
