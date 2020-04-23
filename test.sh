#!/bin/bash

case "$1" in
	0|1|2)
		exec python3 -m raftkv -i $1
		;;
	*)
		exec python3 -m raftkv.client "$@"
		;;
esac
