organization := "bitbiz"
name := "timetracking"
version := "0.1"
isSnapshot := true

scalaVersion := "2.12.6"
libraryDependencies += CommonDeps.threetenextra
libraryDependencies += "com.github.alexarchambault" %% "case-app" % "2.0.0-M3"
libraryDependencies += "com.lihaoyi" %% "scalatags" % "0.6.7"

enablePlugins(JavaAppPackaging)
