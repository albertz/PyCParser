#include <stdio.h>

int main(int argc, char** argv) {
	fprintf(stdout, "Hello world!\n");
	fprintf(stdout, "expr1 = %i\n", -1);
	fprintf(stdout, "expr2 = %i\n", 1 > -1);
	return 0;
}
