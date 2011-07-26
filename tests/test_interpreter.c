#include <stdio.h>

int main(int argc, char** argv) {
	printf("Hello %s! (via printf)\n", "world");
	fprintf(stdout, "%s world%c (via fprintf)\n", "Hello", '!');
	printf("expr1 = %i\n", -1);
	printf("expr2 = %i\n", 1 > -1);
	return 0;
}
